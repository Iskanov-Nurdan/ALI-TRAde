# -*- coding: utf-8 -*-
"""Атака на журнал аудита, отчёты и утечку учётных данных."""
from apps.accounts.models import User, UserRole
from apps.core.models import AuditLog
from apps.deliveries.models import DeliveryEvent

from .base import PASSWORD, AdversarialBase


class AuditCoverage(AdversarialBase):
    """Значимые действия, которых в журнале нет."""

    def test_successful_login_is_written_to_audit_log(self):
        """AuditLog.Action.LOGIN объявлен в модели, но не пишется никогда.

        LoginView — это чистый TokenObtainPairView без обращения к AuditService,
        поэтому «Вход в систему» в журнале не появляется ни разу, и расследовать
        компрометацию учётной записи по журналу невозможно.
        """
        response = self.login(self.admin.login)
        self.assertEqual(response.status_code, 200)

        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.Action.LOGIN).exists(),
            f"журнал пуст: {list(AuditLog.objects.values_list('action', 'entity_type'))}",
        )

    def test_password_change_is_written_to_audit_log(self):
        """Смена пароля не оставляет следа в журнале.

        UserService.change_own_password пишет только в logger, но не в AuditLog,
        в отличие от всех остальных операций над сотрудником.
        """
        self.auth(self.employee)
        response = self.client.post(
            "/api/auth/change-password/",
            {"current_password": PASSWORD, "new_password": "brandNew9876"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        self.assertTrue(
            AuditLog.objects.filter(entity_type="user", user=self.employee).exists(),
            f"журнал пуст: {list(AuditLog.objects.values_list('action', 'entity_type'))}",
        )


class AuditIntegrityOnUserDeletion(AdversarialBase):
    """Удаление сотрудника обезличивает уже записанную историю."""

    def test_deleting_user_keeps_authorship_in_audit_log(self):
        """AuditLog.user = SET_NULL: удалённый администратор исчезает из журнала.

        delete_user запрещает удаление только тем, кто участвовал в рейсах и
        расходах. Администратор, который менял курсы валют и справочники,
        удаляется свободно — и все его записи в журнале аудита становятся
        безымянными.
        """
        rate_admin = User.objects.create_user(
            login="rates", password=PASSWORD, full_name="Курсовой К", role=UserRole.ADMIN
        )
        self.auth(rate_admin)
        changed = self.client.put(
            "/api/expenses/rates/", {"rates": {"USD": "90.0"}}, format="json"
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(
            AuditLog.objects.filter(entity_type="currency_rate", user=rate_admin).count(), 1
        )

        self.auth(self.admin)
        deleted = self.client.delete(f"/api/users/{rate_admin.id}/")
        self.assertEqual(deleted.status_code, 204)

        orphaned = list(
            AuditLog.objects.filter(entity_type="currency_rate").values_list("user_id", flat=True)
        )
        self.assertNotIn(
            None,
            orphaned,
            "после удаления сотрудника его записи в журнале аудита потеряли автора",
        )

    def test_deleting_user_keeps_authorship_of_delivery_comments(self):
        """Комментарии к рейсу теряют автора вместе с удалённым сотрудником.

        Проверка «сотрудник уже участвовал в рейсах» перечисляет
        created/dispatched/received/cancelled_deliveries, created_expenses и
        passed_waypoints, но не delivery_events. Сотрудник, который только
        комментировал рейсы, удаляется — и его комментарии остаются в истории
        без автора, ровно та потеря истории, от которой защищается код.
        """
        delivery = self.make_delivery(actor=self.admin)
        commenter = User.objects.create_user(
            login="talker", password=PASSWORD, full_name="Болтун Болтунов"
        )
        self.auth(commenter)
        posted = self.client.post(
            f"/api/deliveries/{delivery.id}/comments/",
            {"comment": "машину задержали на границе"},
            format="json",
        )
        self.assertEqual(posted.status_code, 201)

        self.auth(self.admin)
        deleted = self.client.delete(f"/api/users/{commenter.id}/")

        event = DeliveryEvent.objects.filter(
            event_type=DeliveryEvent.EventType.COMMENT_ADDED
        ).first()
        self.assertEqual(
            deleted.status_code,
            400,
            f"сотрудник с комментариями удалён (ответ {deleted.status_code}), "
            f"автор комментария теперь {event.user_id!r}",
        )


class ReportFilterValidation(AdversarialBase):
    """Отчёты строятся по невалидированным фильтрам."""

    def setUp(self):
        super().setUp()
        self.make_delivery(number="01KG1111AB")
        self.make_delivery(number="01KG2222AB")

    def test_report_rejects_unknown_status_value(self):
        """Отчёт молча игнорирует нераспознанный фильтр и отдаёт всё подряд.

        AdminReportMixin создаёт DeliveryFilter напрямую и берёт .qs, минуя
        is_valid() из DjangoFilterBackend. Тот же параметр на /api/deliveries/
        даёт 400, а в отчёте — 200 и полная, неотфильтрованная сводка.
        """
        self.auth(self.admin)
        listing = self.client.get("/api/deliveries/?status=НЕТ_ТАКОГО")
        self.assertEqual(listing.status_code, 400, "список рейсов обязан отклонить статус")

        report = self.client.get("/api/reports/summary/?status=НЕТ_ТАКОГО")

        self.assertEqual(
            report.status_code,
            400,
            f"отчёт принял несуществующий статус: {report.data}",
        )

    def test_report_rejects_malformed_date_range(self):
        """Кривая дата в периоде отчёта не отсекается — период просто теряется.

        Администратор запрашивает выгрузку за период, ошибается в формате даты
        и получает 200 с полной выгрузкой за всё время, считая её отчётом за период.
        """
        self.auth(self.admin)

        report = self.client.get("/api/reports/summary/?date_from=2025-13-45")
        export = self.client.get("/api/reports/export/deliveries/?ext=csv&date_from=не-дата")

        self.assertEqual(
            (report.status_code, export.status_code),
            (400, 400),
            f"некорректная дата принята: отчёт — {report.data}, "
            f"выгрузка — {len(export.content)} байт",
        )


class CredentialExposure(AdversarialBase):
    """Логины сотрудников раздаются в обычных списках."""

    def test_delivery_list_does_not_expose_logins(self):
        """EmployeeDirectoryView прячет логины, а список рейсов их отдаёт.

        UserShortSerializer включает поле login и подставляется в created_by,
        dispatched_by, received_by, а также в расходы и историю. Обычный
        сотрудник получает полный список логинов, включая администраторские,
        то есть половину пары для подбора пароля.
        """
        self.make_delivery(actor=self.admin)
        self.auth(self.employee)

        directory = self.client.get("/api/users/directory/")
        self.assertNotIn("login", directory.data[0], "справочник и не должен отдавать логины")

        deliveries = self.client.get("/api/deliveries/")
        created_by = deliveries.data["results"][0]["created_by"]

        self.assertNotIn(
            "login",
            created_by,
            f"логин администратора виден рядовому сотруднику: {created_by}",
        )
