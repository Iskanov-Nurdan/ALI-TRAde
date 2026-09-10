"""Регрессионные тесты: закрепление поведения, найденного адверсариальным разбором.

Файл вырос из набора, который фиксировал дефекты системы. Дефекты исправлены,
и теперь каждый тест утверждает ПРАВИЛЬНОЕ поведение по бизнес-правилам ТЗ:
если правка когда-нибудь откатится, тест упадёт.

Тесты, помеченные @unittest.expectedFailure, описывают места, где правило
Все дефекты, найденные адверсариальным ревью, исправлены — набор закрепляет это.
"""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest import mock

from django.conf import settings as django_settings
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

from apps.accounts.models import User, UserRole
from apps.accounts.views import LoginView
from apps.core.exceptions import BusinessError
from apps.core.models import AuditLog
from apps.core.utils import client_ip
from apps.deliveries.models import (
    Delivery,
    DeliveryEvent,
    DeliveryStatus,
    DeliveryWaypoint,
    normalize_vehicle_number,
)
from apps.deliveries.services import DeliveryService
from apps.expenses.models import Currency, Expense, ExpenseType
from apps.expenses.services import ExpenseService
from apps.points.models import Point

PASSWORD = "secret12345"
LONG_TEXT = "Ы" * 100_000
HTML_PAYLOAD = "<script>alert(document.cookie)</script>"


def make_user(login, role=UserRole.EMPLOYEE):
    return User.objects.create_user(
        login=login, password=PASSWORD, full_name=f"Сотрудник {login}", role=role
    )


class AdversarialBase(TestCase):
    """Общая заготовка: четыре точки, админ, два сотрудника, готовый рейс."""

    def setUp(self):
        self.admin = make_user("adv_admin", role=UserRole.ADMIN)
        self.employee = make_user("adv_employee")
        self.other = make_user("adv_other")
        self.point_a = Point.objects.create(name="Бишкек")
        self.point_b = Point.objects.create(name="Достук")
        self.border = Point.objects.create(name="Граница")
        self.warehouse = Point.objects.create(name="Склад")
        self.service = DeliveryService()
        self.client = APIClient()

    def create_delivery(self, actor=None, **overrides):
        data = {
            "point_from_id": self.point_a.id,
            "point_to_id": self.point_b.id,
            "vehicle_number": "01 KG 1234 AB",
            "dispatched_at": timezone.now(),
            "duration_hours": Decimal("4"),
            "auto_dispatch": True,
        }
        data.update(overrides)
        return self.service.create_delivery(actor=actor or self.employee, data=data)

    def add_expense(self, delivery, amount="10", actor=None):
        return ExpenseService().add_expense(
            actor=actor or self.employee,
            delivery=delivery,
            data={
                "expense_type_id": ExpenseType.objects.first().id,
                "amount": Decimal(amount),
                "currency": Currency.USD,
                "description": "Оплата на границе",
            },
        )

    def auth(self, user):
        response = self.client.post(
            "/api/auth/login/", {"login": user.login, "password": PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")

    def deadline_events(self, delivery):
        return DeliveryEvent.objects.filter(
            delivery=delivery, event_type=DeliveryEvent.EventType.DEADLINE_PASSED
        )


# --------------------------------------------------------------------------- #
#  1. Время, дедлайны и просрочка                                              #
# --------------------------------------------------------------------------- #


class DeadlineAndTimeRules(AdversarialBase):
    """Сроки: будущее время, лимит 30 суток, неустранимость факта просрочки."""

    def test_dispatch_time_in_the_future_is_rejected_on_create(self):
        """Время отправления в будущем при создании рейса отклоняется."""
        with self.assertRaises(BusinessError):
            self.create_delivery(dispatched_at=timezone.now() + timedelta(days=30))
        self.assertEqual(Delivery.objects.count(), 0)

    def test_dispatch_time_in_the_future_is_rejected_on_dispatch(self):
        """Подтверждение отправления будущим временем тоже отклоняется."""
        delivery = self.create_delivery(auto_dispatch=False)
        with self.assertRaises(BusinessError):
            self.service.dispatch(
                actor=self.employee,
                delivery=delivery,
                data={"dispatched_at": timezone.now() + timedelta(days=2)},
            )
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryStatus.CREATED)

    def test_small_clock_skew_in_dispatch_time_is_tolerated(self):
        """Допуск 5 минут: расхождение часов клиента и сервера рейс не ломает."""
        delivery = self.create_delivery(dispatched_at=timezone.now() + timedelta(minutes=2))
        self.assertEqual(delivery.status, DeliveryStatus.IN_TRANSIT)

    def test_receive_time_in_the_future_is_rejected(self):
        """Время прибытия не может быть в будущем."""
        delivery = self.create_delivery()
        with self.assertRaises(BusinessError):
            self.service.receive(
                actor=self.other,
                delivery=delivery,
                data={"received_at": timezone.now() + timedelta(days=5)},
            )
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryStatus.IN_TRANSIT)
        self.assertIsNone(delivery.received_at)

    def test_thirty_days_limit_applies_to_exact_deadline(self):
        """Срок прибытия не больше 30 суток — и для «часов», и для точного времени."""
        dispatched_at = timezone.now()
        with self.assertRaises(BusinessError):
            self.create_delivery(
                dispatched_at=dispatched_at,
                duration_hours=None,
                deadline_at=dispatched_at + timedelta(days=365),
            )
        # Ровно на границе срок ещё принимается.
        delivery = self.create_delivery(
            dispatched_at=dispatched_at,
            duration_hours=None,
            deadline_at=dispatched_at + timedelta(days=30),
        )
        self.assertEqual(delivery.planned_duration_minutes, 30 * 24 * 60)

    def test_thirty_days_limit_applies_on_update(self):
        """Правило 30 суток обязано действовать и при правке рейса администратором.

        ДЕФЕКТ: DeliveryService.update_delivery() присваивает deadline_at напрямую,
        минуя _calc_deadline(), и пересчитывает planned_duration_minutes без верхней
        границы. PATCH с дедлайном через 400 суток проходит с кодом 200.
        """
        delivery = self.create_delivery()
        self.auth(self.admin)
        response = self.client.patch(
            f"/api/deliveries/{delivery.id}/",
            {"deadline_at": (delivery.dispatched_at + timedelta(days=400)).isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_backdated_receive_does_not_erase_logged_overdue(self):
        """Правило 4: подтверждение прибытия не стирает факт просрочки.

        Даже если сотрудник указал received_at раньше дедлайна, событие
        DEADLINE_PASSED остаётся в истории рейса.
        """
        delivery = self.create_delivery(dispatched_at=timezone.now() - timedelta(hours=6))
        self.assertEqual(self.service.sync_overdue_events(), 1)
        delivery.refresh_from_db()

        received = self.service.receive(
            actor=self.employee,
            delivery=delivery,
            data={"received_at": delivery.deadline_at - timedelta(minutes=1)},
        )
        self.assertEqual(received.status, DeliveryStatus.ARRIVED)
        self.assertTrue(self.deadline_events(received).exists())

    def test_backdated_receive_logs_overdue_even_if_it_was_not_synced_yet(self):
        """Правило 3+4: просрочка попадает в историю по РЕАЛЬНОМУ времени.

        Раньше _log_deadline_passed() получал limit_time=received_at, и указанное
        задним числом прибытие вообще не оставляло следа просрочки.
        """
        delivery = self.create_delivery(dispatched_at=timezone.now() - timedelta(hours=6))
        self.assertTrue(delivery.is_overdue)
        self.assertFalse(self.deadline_events(delivery).exists())

        received = self.service.receive(
            actor=self.employee,
            delivery=delivery,
            data={"received_at": delivery.deadline_at - timedelta(minutes=1)},
        )
        self.assertEqual(self.deadline_events(received).count(), 1)

    def test_deadline_passed_event_is_written_once_per_deadline(self):
        """Правило 3: DEADLINE_PASSED пишется один раз на каждый срок.

        Повторные синхронизации по тому же сроку дубля не создают. Но если
        администратор продлил срок и новый срок тоже истёк — это отдельная
        просрочка, и она обязана попасть в историю: иначе рейс числится
        просроченным (is_overdue=True), а история об этом молчит.
        """
        delivery = self.create_delivery(dispatched_at=timezone.now() - timedelta(hours=6))
        self.assertEqual(self.service.sync_overdue_events(), 1)
        delivery.refresh_from_db()
        self.assertTrue(delivery.deadline_passed_logged)

        # Повторные прогоны по тому же сроку дубля не создают.
        self.assertEqual(self.service.sync_overdue_events(), 0)
        self.assertEqual(self.deadline_events(delivery).count(), 1)

        # Админ переносит дедлайн в будущее — рейс снова укладывается в график.
        self.service.update_delivery(
            actor=self.admin,
            delivery=delivery,
            data={"deadline_at": timezone.now() + timedelta(hours=1)},
        )
        delivery.refresh_from_db()
        self.assertFalse(delivery.deadline_passed_logged)
        self.assertEqual(self.deadline_events(delivery).count(), 1)

        # Новый срок тоже истёк — вторая просрочка, вторая запись в истории.
        Delivery.objects.filter(pk=delivery.pk).update(
            deadline_at=timezone.now() - timedelta(minutes=5)
        )
        self.assertEqual(self.service.sync_overdue_events(), 1)
        self.assertEqual(self.deadline_events(delivery).count(), 2)

    def test_deadline_of_arrived_delivery_cannot_be_moved(self):
        """Опоздание фиксируется навсегда: сроки прибывшего рейса не правятся."""
        delivery = self.create_delivery(dispatched_at=timezone.now() - timedelta(hours=6))
        received = self.service.receive(actor=self.other, delivery=delivery, data={})
        self.assertTrue(received.arrived_late)

        with self.assertRaises(BusinessError):
            self.service.update_delivery(
                actor=self.admin,
                delivery=received,
                data={"deadline_at": received.received_at + timedelta(hours=1)},
            )
        received.refresh_from_db()
        self.assertTrue(received.arrived_late)
        self.assertGreater(received.late_minutes, 0)
        self.assertEqual(received.state_label, "Прибыл с опозданием")

    def test_deadline_of_cancelled_delivery_cannot_be_moved(self):
        """У отменённого рейса сроки тоже заморожены."""
        delivery = self.create_delivery()
        self.service.cancel(
            actor=self.admin, delivery=delivery, data={"comment": "Машина сломалась"}
        )
        with self.assertRaises(BusinessError):
            self.service.update_delivery(
                actor=self.admin,
                delivery=delivery,
                data={"duration_hours": Decimal("10")},
            )

    def test_non_time_fields_of_finished_delivery_are_still_editable(self):
        """Заморожены именно сроки: опечатку в номере машины исправить можно."""
        delivery = self.create_delivery()
        self.service.receive(actor=self.other, delivery=delivery, data={})
        updated = self.service.update_delivery(
            actor=self.admin, delivery=delivery, data={"vehicle_number": "02 KG 5555 CD"}
        )
        self.assertEqual(updated.vehicle_number, "02 KG 5555 CD")


# --------------------------------------------------------------------------- #
#  2. Маршрут и промежуточные точки                                            #
# --------------------------------------------------------------------------- #


class RouteRules(AdversarialBase):
    def _with_waypoints(self, ids=None, **overrides):
        return self.create_delivery(
            waypoint_ids=ids if ids is not None else [self.border.id], **overrides
        )

    def test_point_from_cannot_be_changed_to_existing_waypoint(self):
        """Точка отправления не может совпадать с промежуточной — и при правке тоже."""
        delivery = self._with_waypoints([self.border.id])
        with self.assertRaises(BusinessError):
            self.service.update_delivery(
                actor=self.admin, delivery=delivery, data={"point_from_id": self.border.id}
            )
        delivery.refresh_from_db()
        self.assertEqual(delivery.route_points, ["Бишкек", "Граница", "Достук"])

    def test_point_to_cannot_be_changed_to_existing_waypoint(self):
        """То же самое для точки прибытия."""
        delivery = self._with_waypoints([self.border.id])
        with self.assertRaises(BusinessError):
            self.service.update_delivery(
                actor=self.admin, delivery=delivery, data={"point_to_id": self.border.id}
            )
        delivery.refresh_from_db()
        self.assertEqual(delivery.route_points, ["Бишкек", "Граница", "Достук"])

    def test_route_edges_and_waypoints_can_be_swapped_together(self):
        """Правка допустима, если маршрут остаётся корректным целиком."""
        delivery = self._with_waypoints([self.border.id])
        self.service.update_delivery(
            actor=self.admin,
            delivery=delivery,
            data={"point_from_id": self.border.id, "waypoint_ids": [self.warehouse.id]},
        )
        delivery.refresh_from_db()
        self.assertEqual(delivery.route_points, ["Граница", "Склад", "Достук"])

    def test_waypoints_must_be_passed_in_order(self):
        """Точки маршрута проходятся строго в заданном порядке."""
        delivery = self._with_waypoints([self.border.id, self.warehouse.id])
        first, second = list(delivery.waypoints.all())

        with self.assertRaises(BusinessError):
            self.service.pass_waypoint(
                actor=self.employee, delivery=delivery, waypoint=second, data={}
            )
        second.refresh_from_db()
        self.assertFalse(second.is_passed)

        # После первой точки вторая отмечается свободно.
        self.service.pass_waypoint(
            actor=self.employee, delivery=delivery, waypoint=first, data={}
        )
        self.service.pass_waypoint(
            actor=self.employee, delivery=delivery, waypoint=second, data={}
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.is_passed)
        self.assertTrue(second.is_passed)

    def test_waypoint_cannot_be_passed_in_the_future(self):
        """Время прохождения точки не может быть в будущем."""
        delivery = self._with_waypoints([self.border.id])
        waypoint = delivery.waypoints.first()
        with self.assertRaises(BusinessError):
            self.service.pass_waypoint(
                actor=self.employee,
                delivery=delivery,
                waypoint=waypoint,
                data={"passed_at": timezone.now() + timedelta(days=3)},
            )
        waypoint.refresh_from_db()
        self.assertIsNone(waypoint.passed_at)

    def test_point_used_only_as_waypoint_cannot_be_deleted(self):
        """Точка, занятая только как промежуточная, не удаляется: 400 с пояснением."""
        self._with_waypoints([self.border.id])
        self.auth(self.admin)
        response = self.client.delete(f"/api/points/{self.border.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("рейс", response.data["detail"].lower())
        self.assertTrue(Point.objects.filter(pk=self.border.id).exists())

    def test_unused_point_is_still_deletable(self):
        """Свободная точка удаляется как раньше — проверка не стала слишком строгой."""
        spare = Point.objects.create(name="Резервная точка")
        self.auth(self.admin)
        response = self.client.delete(f"/api/points/{spare.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Point.objects.filter(pk=spare.id).exists())


# --------------------------------------------------------------------------- #
#  3. Аудит и целостность                                                      #
# --------------------------------------------------------------------------- #


class AuditAndIntegrityRules(AdversarialBase):
    def test_delivery_deletion_is_written_to_audit_log(self):
        """Правило 9: удаление рейса попадает в журнал аудита со снимком данных."""
        delivery = self.create_delivery()
        self.add_expense(delivery, "500")
        delivery_id = delivery.id

        self.auth(self.admin)
        response = self.client.delete(f"/api/deliveries/{delivery_id}/")
        self.assertEqual(response.status_code, 204)

        self.assertFalse(Delivery.objects.filter(pk=delivery_id).exists())
        self.assertFalse(Expense.objects.filter(delivery_id=delivery_id).exists())
        self.assertFalse(DeliveryEvent.objects.filter(delivery_id=delivery_id).exists())

        entries = AuditLog.objects.filter(
            entity_type="delivery",
            entity_id=str(delivery_id),
            action=AuditLog.Action.DELETE,
        )
        self.assertEqual(entries.count(), 1)
        snapshot = entries.first().old_value
        self.assertEqual(snapshot["vehicle_number"], "01 KG 1234 AB")
        self.assertEqual(snapshot["route"], "Бишкек → Достук")
        self.assertEqual(snapshot["expenses_count"], 1)
        self.assertEqual(entries.first().user_id, self.admin.id)

    def test_deleting_employee_with_deliveries_returns_readable_error(self):
        """Сотрудника с историей не удаляют: 400 и понятное объяснение, а не 409."""
        self.create_delivery(actor=self.employee)
        self.auth(self.admin)
        response = self.client.delete(f"/api/users/{self.employee.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "business_error")
        self.assertIn("истори", response.data["detail"].lower())
        self.assertTrue(User.objects.filter(pk=self.employee.id).exists())

    def test_employee_without_history_can_still_be_deleted(self):
        """Сотрудник, ничего не сделавший в системе, удаляется без препятствий."""
        self.auth(self.admin)
        response = self.client.delete(f"/api/users/{self.other.id}/")
        self.assertEqual(response.status_code, 204)

    def test_repository_treats_non_numeric_id_as_not_found(self):
        """BaseRepository.get_by_id() гасит ValueError из ORM: мусор — это «не найдено»."""
        from apps.deliveries.repositories import DeliveryRepository

        self.assertIsNone(DeliveryRepository().get_by_id("abc"))
        self.assertIsNone(DeliveryRepository().get_by_id("'; DROP TABLE deliveries; --"))

    def test_non_numeric_delivery_id_returns_not_found(self):
        """Мусор вместо идентификатора рейса должен давать 404, а не 500.

        ДЕФЕКТ: DeliveryViewSet.retrieve() обращается к
        DeliveryRepository.get_detail(), который, в отличие от
        BaseRepository.get_by_id(), не перехватывает ValueError из ORM.
        GET /api/deliveries/abc/ падает с «invalid literal for int()» и
        превращается обработчиком в 500 server_error.
        """
        self.auth(self.employee)
        response = self.client.get("/api/deliveries/abc/")
        self.assertEqual(response.status_code, 404)

    @override_settings(TRUST_PROXY_IP_HEADER=False)
    def test_forwarded_ip_header_is_ignored_without_trusted_proxy(self):
        """X-Forwarded-For учитывается только при TRUST_PROXY_IP_HEADER=True."""
        self.auth(self.employee)
        response = self.client.post(
            "/api/deliveries/",
            {
                "point_from_id": self.point_a.id,
                "point_to_id": self.point_b.id,
                "vehicle_number": "01 KG 7777 ZZ",
                "duration_hours": "4",
            },
            format="json",
            HTTP_X_FORWARDED_FOR="203.0.113.7",
        )
        self.assertEqual(response.status_code, 201)
        entry = AuditLog.objects.filter(entity_type="delivery").latest("created_at")
        self.assertEqual(entry.ip_address, "127.0.0.1")

    @override_settings(TRUST_PROXY_IP_HEADER=True)
    def test_forwarded_ip_header_is_used_behind_trusted_proxy(self):
        """За доверенным прокси берётся первый корректный адрес из заголовка."""
        self.auth(self.employee)
        response = self.client.post(
            "/api/deliveries/",
            {
                "point_from_id": self.point_a.id,
                "point_to_id": self.point_b.id,
                "vehicle_number": "01 KG 7777 ZZ",
                "duration_hours": "4",
            },
            format="json",
            HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1",
        )
        self.assertEqual(response.status_code, 201)
        entry = AuditLog.objects.filter(entity_type="delivery").latest("created_at")
        self.assertEqual(entry.ip_address, "203.0.113.7")

    @override_settings(TRUST_PROXY_IP_HEADER=True)
    def test_spoofed_ip_header_falls_back_to_remote_addr(self):
        """Подделанный заголовок не попадает в базу: берётся REMOTE_ADDR."""
        self.auth(self.employee)
        response = self.client.post(
            "/api/deliveries/",
            {
                "point_from_id": self.point_a.id,
                "point_to_id": self.point_b.id,
                "vehicle_number": "01 KG 7777 ZZ",
                "duration_hours": "4",
            },
            format="json",
            HTTP_X_FORWARDED_FOR="не-ip-адрес",
        )
        self.assertEqual(response.status_code, 201)
        entry = AuditLog.objects.filter(entity_type="delivery").latest("created_at")
        self.assertEqual(entry.ip_address, "127.0.0.1")

    def test_client_ip_returns_none_for_garbage_values(self):
        """Если корректного адреса нет вообще — в аудит пишется NULL, а не мусор."""
        request = RequestFactory().get("/")
        request.META["REMOTE_ADDR"] = "не-ip-адрес"
        self.assertIsNone(client_ip(request))

    def test_login_view_declares_rate_limit_scope(self):
        """Вход ограничен по частоте: у LoginView есть scope и ScopedRateThrottle."""
        self.assertEqual(LoginView.throttle_scope, "login")
        self.assertIn(ScopedRateThrottle, [type(t) for t in LoginView().get_throttles()])
        self.assertIn("login", django_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])

    def test_password_bruteforce_is_throttled(self):
        """Перебор пароля упирается в 429.

        В settings.py лимиты отключены на время тестов, поэтому здесь ставится
        собственный лимит: проверяется именно связка «scope + ScopedRateThrottle».
        """
        cache.clear()
        self.addCleanup(cache.clear)
        rates = {"login": "5/min", "anon": None}
        with mock.patch.object(SimpleRateThrottle, "THROTTLE_RATES", rates):
            codes = [
                self.client.post(
                    "/api/auth/login/",
                    {"login": self.employee.login, "password": f"wrong-{index}"},
                    format="json",
                ).status_code
                for index in range(7)
            ]
        self.assertEqual(codes[:5], [401] * 5)
        self.assertEqual(codes[5:], [429, 429])


# --------------------------------------------------------------------------- #
#  4. Гонки и идемпотентность                                                  #
# --------------------------------------------------------------------------- #


class ConcurrencyRules(AdversarialBase):
    """Сервисы перечитывают объект с select_for_update: устаревшая копия не проходит."""

    def test_second_parallel_receive_is_rejected(self):
        """Второй приём по устаревшей копии рейса отклоняется."""
        delivery = self.create_delivery()
        first_copy = Delivery.objects.get(pk=delivery.id)
        second_copy = Delivery.objects.get(pk=delivery.id)

        self.service.receive(actor=self.employee, delivery=first_copy, data={})
        with self.assertRaises(BusinessError):
            self.service.receive(actor=self.other, delivery=second_copy, data={})

        delivery.refresh_from_db()
        self.assertEqual(delivery.received_by_id, self.employee.id)
        self.assertEqual(
            DeliveryEvent.objects.filter(
                delivery=delivery, event_type=DeliveryEvent.EventType.RECEIVED
            ).count(),
            1,
        )

    def test_second_parallel_waypoint_pass_is_rejected(self):
        """Повторная отметка той же точки отклоняется."""
        delivery = self.create_delivery(waypoint_ids=[self.border.id])
        waypoint_a = delivery.waypoints.first()
        waypoint_b = DeliveryWaypoint.objects.get(pk=waypoint_a.id)

        self.service.pass_waypoint(
            actor=self.employee, delivery=delivery, waypoint=waypoint_a, data={}
        )
        with self.assertRaises(BusinessError):
            self.service.pass_waypoint(
                actor=self.other, delivery=delivery, waypoint=waypoint_b, data={}
            )

        self.assertEqual(
            DeliveryEvent.objects.filter(
                delivery=delivery, event_type=DeliveryEvent.EventType.WAYPOINT_PASSED
            ).count(),
            1,
        )
        waypoint_a.refresh_from_db()
        self.assertEqual(waypoint_a.passed_by_id, self.employee.id)

    def test_second_parallel_dispatch_is_rejected(self):
        """Повторное подтверждение отправления отклоняется."""
        delivery = self.create_delivery(auto_dispatch=False)
        copy_a = Delivery.objects.get(pk=delivery.id)
        copy_b = Delivery.objects.get(pk=delivery.id)

        self.service.dispatch(actor=self.employee, delivery=copy_a, data={})
        with self.assertRaises(BusinessError):
            self.service.dispatch(actor=self.other, delivery=copy_b, data={})

        self.assertEqual(
            DeliveryEvent.objects.filter(
                delivery=delivery, event_type=DeliveryEvent.EventType.DISPATCHED
            ).count(),
            1,
        )

    def test_second_parallel_cancel_is_rejected(self):
        """Повторная отмена рейса отклоняется."""
        delivery = self.create_delivery()
        copy_a = Delivery.objects.get(pk=delivery.id)
        copy_b = Delivery.objects.get(pk=delivery.id)

        self.service.cancel(actor=self.admin, delivery=copy_a, data={"comment": "Поломка"})
        with self.assertRaises(BusinessError):
            self.service.cancel(actor=self.admin, delivery=copy_b, data={"comment": "Ещё раз"})

        delivery.refresh_from_db()
        self.assertEqual(delivery.cancel_comment, "Поломка")

    def test_update_over_stale_copy_sees_actual_status(self):
        """Правка по устаревшей копии видит уже изменившийся статус рейса."""
        delivery = self.create_delivery()
        stale_copy = Delivery.objects.get(pk=delivery.id)
        self.service.receive(actor=self.employee, delivery=delivery, data={})

        self.assertEqual(stale_copy.status, DeliveryStatus.IN_TRANSIT)
        with self.assertRaises(BusinessError):
            self.service.update_delivery(
                actor=self.admin,
                delivery=stale_copy,
                data={"deadline_at": timezone.now() + timedelta(hours=5)},
            )


# --------------------------------------------------------------------------- #
#  5. Расходы                                                                  #
# --------------------------------------------------------------------------- #


class ExpenseRules(AdversarialBase):
    def test_expense_with_broken_delivery_id_returns_not_found(self):
        """Мусорный идентификатор рейса в расходе — 404, а не 500."""
        self.auth(self.employee)
        response = self.client.post(
            "/api/expenses/",
            {
                "delivery": "'; DROP TABLE deliveries; --",
                "expense_type_id": ExpenseType.objects.first().id,
                "amount": "10.00",
                "description": "Проверка",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Expense.objects.count(), 0)

    def test_expense_cannot_be_added_to_cancelled_delivery(self):
        """Расход добавляется на любом этапе живого рейса, но не к отменённому."""
        delivery = self.create_delivery()
        self.service.cancel(
            actor=self.admin, delivery=delivery, data={"comment": "Машина сломалась"}
        )
        delivery.refresh_from_db()

        self.auth(self.employee)
        response = self.client.post(
            f"/api/deliveries/{delivery.id}/expenses/",
            {
                "expense_type_id": ExpenseType.objects.first().id,
                "amount": "999.99",
                "currency": "USD",
                "description": "Расход по отменённому рейсу",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "business_error")
        self.assertEqual(Expense.objects.filter(delivery=delivery).count(), 0)

    def test_expense_is_allowed_after_arrival(self):
        """Прибывший рейс расходы принимает — запрет касается только отмены."""
        delivery = self.create_delivery()
        self.service.receive(actor=self.employee, delivery=delivery, data={})
        delivery.refresh_from_db()
        expense = self.add_expense(delivery, "42")
        self.assertEqual(expense.delivery_id, delivery.id)

    def _enable_payer_rule(self):
        from apps.expenses.models import ExpenseSettings, Payer

        settings = ExpenseSettings.load()
        settings.auto_payer_enabled = True
        settings.threshold_amount = Decimal("50")
        settings.threshold_currency = Currency.USD
        settings.payer_above = Payer.CHINA
        settings.payer_below = Payer.DRIVER
        settings.save()
        return settings

    def _add(self, delivery, **overrides):
        data = {
            "expense_type_id": ExpenseType.objects.first().id,
            "amount": Decimal("1000"),
            "currency": Currency.KGS,
            "description": "Сомовый расход",
        }
        data.update(overrides)
        return ExpenseService().add_expense(actor=self.employee, delivery=delivery, data=data)

    def test_payer_rule_falls_back_to_default_payer_for_other_currency(self):
        """Валюта расхода не совпала с валютой порога — берётся payer_below.

        Раньше плательщик молча подменялся на COMPANY, минуя настройку.
        """
        from apps.expenses.models import Payer

        self._enable_payer_rule()
        delivery = self.create_delivery()
        expense = self._add(delivery)
        self.assertEqual(expense.payer, Payer.DRIVER)
        self.assertTrue(expense.payer_auto_assigned)

    def test_payer_rule_applies_above_and_below_threshold(self):
        """В «своей» валюте правило работает по порогу."""
        from apps.expenses.models import Payer

        self._enable_payer_rule()
        delivery = self.create_delivery()

        above = self._add(delivery, amount=Decimal("100"), currency=Currency.USD)
        self.assertEqual(above.payer, Payer.CHINA)
        self.assertTrue(above.payer_auto_assigned)

        below = self._add(delivery, amount=Decimal("10"), currency=Currency.USD)
        self.assertEqual(below.payer, Payer.DRIVER)
        self.assertTrue(below.payer_auto_assigned)

    def test_manual_payer_wins_over_rule(self):
        """Ручной выбор плательщика всегда сильнее автоматического правила."""
        from apps.expenses.models import Payer

        self._enable_payer_rule()
        delivery = self.create_delivery()
        expense = self._add(
            delivery, amount=Decimal("1000"), currency=Currency.USD, payer=Payer.COMPANY
        )
        self.assertEqual(expense.payer, Payer.COMPANY)
        self.assertFalse(expense.payer_auto_assigned)

    def test_payer_defaults_to_company_when_rule_is_disabled(self):
        """Правило выключено — плательщик по умолчанию, без отметки «автоматически»."""
        from apps.expenses.models import Payer

        delivery = self.create_delivery()
        expense = self._add(delivery)
        self.assertEqual(expense.payer, Payer.COMPANY)
        self.assertFalse(expense.payer_auto_assigned)


# --------------------------------------------------------------------------- #
#  6. Экспорт: инъекция формул                                                 #
# --------------------------------------------------------------------------- #


class ExportInjectionRules(AdversarialBase):
    PAYLOAD = "=CMD|'/C CALC'!A0"

    def test_csv_export_escapes_formula_prefix(self):
        """Значения, начинающиеся с = + - @, экранируются апострофом при выгрузке."""
        self.create_delivery(vehicle_number=self.PAYLOAD)
        self.auth(self.admin)
        response = self.client.get("/api/reports/export/deliveries/?ext=csv")
        self.assertEqual(response.status_code, 200)

        body = response.content.decode("utf-8-sig")
        cells = body.splitlines()[1].split(";")
        self.assertIn("'" + self.PAYLOAD, cells)
        self.assertFalse(any(cell.startswith(("=", "+", "@")) for cell in cells))

    def test_xlsx_export_does_not_write_active_formula_cell(self):
        """В книге Excel ячейка остаётся текстом, а не формулой (data_type != 'f')."""
        self.create_delivery(vehicle_number=self.PAYLOAD)
        self.auth(self.admin)
        response = self.client.get("/api/reports/export/deliveries/")
        self.assertEqual(response.status_code, 200)

        workbook = load_workbook(BytesIO(response.content))
        sheet = workbook.active
        cell = sheet.cell(row=2, column=2)
        self.assertEqual(cell.value, "'" + self.PAYLOAD)
        self.assertNotEqual(cell.data_type, "f")

    def test_expense_description_is_escaped_in_csv(self):
        """Тот же вектор через описание расхода тоже обезврежен."""
        payload = "@SUM(1+1)*cmd|'/C calc'!A0"
        delivery = self.create_delivery()
        ExpenseService().add_expense(
            actor=self.employee,
            delivery=delivery,
            data={
                "expense_type_id": ExpenseType.objects.first().id,
                "amount": Decimal("10"),
                "currency": Currency.USD,
                "description": payload,
            },
        )
        self.auth(self.admin)
        response = self.client.get("/api/reports/export/expenses/?ext=csv")
        body = response.content.decode("utf-8-sig")
        self.assertIn("'" + payload, body)
        self.assertNotIn(";" + payload, body)

    def test_ordinary_values_are_not_mangled_by_sanitizer(self):
        """Обычные значения апострофом не портятся."""
        self.create_delivery(vehicle_number="01 KG 1234 AB")
        self.auth(self.admin)
        response = self.client.get("/api/reports/export/deliveries/?ext=csv")
        cells = response.content.decode("utf-8-sig").splitlines()[1].split(";")
        self.assertIn("01 KG 1234 AB", cells)


# --------------------------------------------------------------------------- #
#  7. Поиск и фильтры                                                          #
# --------------------------------------------------------------------------- #


class SearchAndFilterRules(AdversarialBase):
    def test_cyrillic_and_latin_plates_are_the_same_vehicle(self):
        """«01 КГ 1234 АВ» и «01 KG 1234 AB» — одна машина в поиске."""
        self.assertEqual(normalize_vehicle_number("01 КГ 1234 АВ"), "01KG1234AB")
        self.assertEqual(
            normalize_vehicle_number("01 КГ 1234 АВ"), normalize_vehicle_number("01 KG 1234 AB")
        )

        self.create_delivery(vehicle_number="01 КГ 1234 АВ")  # кириллица
        self.create_delivery(vehicle_number="01 KG 1234 AB")  # латиница

        self.auth(self.employee)
        latin = self.client.get("/api/vehicles/search/?q=1234AB")
        self.assertEqual(latin.status_code, 200)
        self.assertEqual(latin.data["count"], 2)

        cyrillic = self.client.get("/api/vehicles/search/?q=1234АВ")
        self.assertEqual(cyrillic.status_code, 200)
        self.assertEqual(cyrillic.data["count"], 2)

    def test_punctuation_only_filter_returns_nothing(self):
        """Фильтр по заведомо несуществующему номеру возвращает пустой список."""
        self.create_delivery()
        self.create_delivery(vehicle_number="02 KG 5555 CD")

        self.auth(self.employee)
        response = self.client.get("/api/deliveries/?vehicle_number=---")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)

    def test_blank_vehicle_filter_does_not_narrow_the_list(self):
        """Пустое значение фильтра — это «без фильтра», а не «ничего не найдено»."""
        self.create_delivery()
        self.auth(self.employee)
        response = self.client.get("/api/deliveries/?vehicle_number=")
        self.assertEqual(response.data["count"], 1)

    def test_vehicle_number_of_pure_punctuation_is_rejected(self):
        """Номер машины обязан содержать буквы или цифры."""
        self.auth(self.employee)
        response = self.client.post(
            "/api/deliveries/",
            {
                "point_from_id": self.point_a.id,
                "point_to_id": self.point_b.id,
                "vehicle_number": "!!!",
                "duration_hours": "4",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "validation_error")
        self.assertIn("vehicle_number", response.data["errors"])
        self.assertEqual(Delivery.objects.count(), 0)


# --------------------------------------------------------------------------- #
#  8. Права доступа и валидация ввода                                          #
# --------------------------------------------------------------------------- #


class PermissionAndInputRules(AdversarialBase):
    def test_employee_cannot_cancel_foreign_delivery(self):
        """Сотрудник отменяет только рейс, который создал сам."""
        delivery = self.create_delivery(actor=self.employee)
        self.auth(self.other)
        response = self.client.post(
            f"/api/deliveries/{delivery.id}/cancel/", {"comment": "Просто так"}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryStatus.IN_TRANSIT)

    def test_employee_can_cancel_own_delivery(self):
        """Свой рейс сотрудник отменить может."""
        delivery = self.create_delivery(actor=self.employee)
        self.auth(self.employee)
        response = self.client.post(
            f"/api/deliveries/{delivery.id}/cancel/", {"comment": "Машина сломалась"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryStatus.CANCELLED)
        self.assertEqual(delivery.cancelled_by_id, self.employee.id)

    def test_admin_can_cancel_any_delivery(self):
        """Администратору доступна отмена любого рейса."""
        delivery = self.create_delivery(actor=self.employee)
        self.auth(self.admin)
        response = self.client.post(
            f"/api/deliveries/{delivery.id}/cancel/", {"comment": "Отмена рейса"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        delivery.refresh_from_db()
        self.assertEqual(delivery.cancelled_by_id, self.admin.id)

    def test_employee_directory_hides_logins(self):
        """/api/users/directory/ отдаёт только имена: логины наружу не уходят."""
        self.auth(self.employee)
        self.assertEqual(self.client.get("/api/users/").status_code, 403)

        directory = self.client.get("/api/users/directory/")
        self.assertEqual(directory.status_code, 200)
        self.assertTrue(directory.data)
        for row in directory.data:
            self.assertEqual(set(row), {"id", "full_name", "short_name"})

    def test_comment_length_is_limited_everywhere(self):
        """Длина комментария ограничена во всех точках ввода."""
        self.auth(self.employee)
        delivery = self.create_delivery(actor=self.employee, auto_dispatch=False,
                                        waypoint_ids=[self.border.id])
        waypoint = delivery.waypoints.first()

        cases = {
            "create": (
                "/api/deliveries/",
                {
                    "point_from_id": self.point_a.id,
                    "point_to_id": self.point_b.id,
                    "vehicle_number": "03 KG 9999 XX",
                    "duration_hours": "4",
                    "comment": LONG_TEXT,
                },
            ),
            "dispatch": (f"/api/deliveries/{delivery.id}/dispatch/", {"comment": LONG_TEXT}),
            "waypoint": (
                f"/api/deliveries/{delivery.id}/waypoints/{waypoint.id}/pass/",
                {"comment": LONG_TEXT},
            ),
            "comment": (f"/api/deliveries/{delivery.id}/comments/", {"comment": LONG_TEXT}),
            "cancel": (f"/api/deliveries/{delivery.id}/cancel/", {"comment": LONG_TEXT}),
            "expense": (
                f"/api/deliveries/{delivery.id}/expenses/",
                {
                    "expense_type_id": ExpenseType.objects.first().id,
                    "amount": "10.00",
                    "currency": "USD",
                    "description": "Проверка",
                    "comment": LONG_TEXT,
                },
            ),
        }
        for label, (url, payload) in cases.items():
            response = self.client.post(url, payload, format="json")
            self.assertEqual(response.status_code, 400, f"{label}: {response.data}")

        # Приём — отдельно: рейс сначала нужно отправить.
        self.service.dispatch(actor=self.employee, delivery=delivery, data={})
        response = self.client.post(
            f"/api/deliveries/{delivery.id}/receive/", {"comment": LONG_TEXT}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_reasonable_comment_is_still_accepted(self):
        """Ограничение не мешает обычному комментарию."""
        delivery = self.create_delivery(actor=self.employee)
        self.auth(self.employee)
        response = self.client.post(
            f"/api/deliveries/{delivery.id}/comments/", {"comment": "Ы" * 2000}, format="json"
        )
        self.assertEqual(response.status_code, 201)

    def test_html_markup_is_rejected_in_delivery_comment(self):
        """Комментарий к рейсу с HTML-разметкой не сохраняется."""
        delivery = self.create_delivery()
        self.auth(self.employee)
        response = self.client.post(
            f"/api/deliveries/{delivery.id}/comments/", {"comment": HTML_PAYLOAD}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            DeliveryEvent.objects.filter(
                delivery=delivery, event_type=DeliveryEvent.EventType.COMMENT_ADDED
            ).exists()
        )

    def test_html_markup_is_rejected_in_dispatch_receive_and_cancel(self):
        """Разметка отклоняется и в комментариях этапов рейса."""
        delivery = self.create_delivery(actor=self.employee, auto_dispatch=False)
        self.auth(self.employee)

        self.assertEqual(
            self.client.post(
                f"/api/deliveries/{delivery.id}/dispatch/", {"comment": HTML_PAYLOAD}, format="json"
            ).status_code,
            400,
        )
        self.service.dispatch(actor=self.employee, delivery=delivery, data={})
        self.assertEqual(
            self.client.post(
                f"/api/deliveries/{delivery.id}/receive/", {"comment": HTML_PAYLOAD}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                f"/api/deliveries/{delivery.id}/cancel/", {"comment": HTML_PAYLOAD}, format="json"
            ).status_code,
            400,
        )

    def test_html_markup_is_rejected_in_expense_description(self):
        """Описание расхода тоже проходит через plain_text."""
        delivery = self.create_delivery()
        self.auth(self.employee)
        response = self.client.post(
            f"/api/deliveries/{delivery.id}/expenses/",
            {
                "expense_type_id": ExpenseType.objects.first().id,
                "amount": "10.00",
                "currency": "USD",
                "description": HTML_PAYLOAD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Expense.objects.count(), 0)

    def test_html_markup_is_rejected_in_point_fields(self):
        """Название и описание точки очищаются от разметки."""
        self.auth(self.admin)
        self.assertEqual(
            self.client.post(
                "/api/points/", {"name": HTML_PAYLOAD}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/points/",
                {"name": "Новая точка", "description": HTML_PAYLOAD},
                format="json",
            ).status_code,
            400,
        )
        self.assertFalse(Point.objects.filter(name="Новая точка").exists())

    def test_html_markup_is_rejected_in_waypoint_comment(self):
        """Комментарий при прохождении точки тоже обязан быть без разметки.

        ДЕФЕКТ: PassWaypointSerializer ограничивает длину (max_length=2000),
        но не вызывает apps.core.validators.plain_text, поэтому <script> в
        комментарии к промежуточной точке сохраняется как есть.
        """
        delivery = self.create_delivery(waypoint_ids=[self.border.id])
        waypoint = delivery.waypoints.first()
        self.auth(self.employee)
        response = self.client.post(
            f"/api/deliveries/{delivery.id}/waypoints/{waypoint.id}/pass/",
            {"comment": HTML_PAYLOAD},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_html_markup_is_rejected_in_create_delivery_comment(self):
        """Комментарий при создании рейса тоже должен отклонять разметку.

        ДЕФЕКТ: DeliveryCreateSerializer.comment не проходит через plain_text
        (в отличие от DispatchSerializer/ReceiveSerializer/CommentSerializer).
        """
        self.auth(self.employee)
        response = self.client.post(
            "/api/deliveries/",
            {
                "point_from_id": self.point_a.id,
                "point_to_id": self.point_b.id,
                "vehicle_number": "01 KG 1234 AB",
                "duration_hours": "4",
                "comment": HTML_PAYLOAD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)


# --------------------------------------------------------------------------- #
#  9. Атаки, которые система отбила изначально                                  #
# --------------------------------------------------------------------------- #


class AttacksThatFailed(AdversarialBase):
    """Здесь система вела себя правильно с самого начала — закрепляем поведение."""

    def test_blocked_employee_token_stops_working(self):
        self.auth(self.employee)
        self.assertEqual(self.client.get("/api/deliveries/").status_code, 200)

        self.employee.is_active = False
        self.employee.save(update_fields=["is_active"])
        self.assertEqual(self.client.get("/api/deliveries/").status_code, 401)

    def test_employee_cannot_reach_admin_only_endpoints(self):
        delivery = self.create_delivery()
        expense = self.add_expense(delivery)
        self.auth(self.other)

        self.assertEqual(self.client.get("/api/audit/").status_code, 403)
        self.assertEqual(self.client.get("/api/reports/summary/").status_code, 403)
        self.assertEqual(self.client.get("/api/reports/export/deliveries/").status_code, 403)
        self.assertEqual(self.client.get("/api/users/").status_code, 403)
        self.assertEqual(
            self.client.patch(
                f"/api/deliveries/{delivery.id}/", {"vehicle_number": "XX 1"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(self.client.delete(f"/api/deliveries/{delivery.id}/").status_code, 403)
        self.assertEqual(
            self.client.patch(
                f"/api/expenses/{expense.id}/", {"amount": "1.00"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(self.client.delete(f"/api/expenses/{expense.id}/").status_code, 403)
        self.assertEqual(
            self.client.put(
                "/api/expenses/settings/", {"auto_payer_enabled": True}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/expense-types/", {"name": "Новый тип"}, format="json").status_code,
            403,
        )

    def test_waypoint_of_another_delivery_is_not_accepted(self):
        mine = self.create_delivery(waypoint_ids=[self.border.id])
        foreign = self.create_delivery(waypoint_ids=[self.warehouse.id])
        foreign_waypoint = foreign.waypoints.first()

        self.auth(self.employee)
        response = self.client.post(
            f"/api/deliveries/{mine.id}/waypoints/{foreign_waypoint.id}/pass/", {}, format="json"
        )
        self.assertEqual(response.status_code, 404)
        foreign_waypoint.refresh_from_db()
        self.assertIsNone(foreign_waypoint.passed_at)

    def test_more_than_ten_waypoints_rejected(self):
        points = [Point.objects.create(name=f"Точка {i}") for i in range(11)]
        self.auth(self.employee)
        response = self.client.post(
            "/api/deliveries/",
            {
                "point_from_id": self.point_a.id,
                "point_to_id": self.point_b.id,
                "vehicle_number": "01 KG 1234 AB",
                "duration_hours": "4",
                "waypoint_ids": [p.id for p in points],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_bad_expense_amounts_rejected(self):
        delivery = self.create_delivery()
        self.auth(self.employee)
        for amount in ("0", "-100.00", "0.001", "не число", "99999999999999.99", "1e20"):
            response = self.client.post(
                f"/api/deliveries/{delivery.id}/expenses/",
                {
                    "expense_type_id": ExpenseType.objects.first().id,
                    "amount": amount,
                    "currency": "USD",
                    "description": "Проверка",
                },
                format="json",
            )
            self.assertEqual(response.status_code, 400, f"amount={amount}")
        self.assertEqual(Expense.objects.count(), 0)

    def test_receive_earlier_than_dispatch_rejected(self):
        delivery = self.create_delivery()
        self.auth(self.employee)
        response = self.client.post(
            f"/api/deliveries/{delivery.id}/receive/",
            {"received_at": (delivery.dispatched_at - timedelta(hours=1)).isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_negative_and_oversized_durations_rejected(self):
        self.auth(self.employee)
        for payload in ({"duration_hours": "-5"}, {"duration_hours": "0"}, {"duration_hours": "800"}):
            body = {
                "point_from_id": self.point_a.id,
                "point_to_id": self.point_b.id,
                "vehicle_number": "01 KG 1234 AB",
            }
            body.update(payload)
            response = self.client.post("/api/deliveries/", body, format="json")
            self.assertEqual(response.status_code, 400, payload)

    def test_ordering_and_page_size_are_whitelisted(self):
        self.create_delivery()
        self.auth(self.employee)
        # Сортировка по произвольному полю игнорируется, а не выполняется.
        self.assertEqual(
            self.client.get("/api/deliveries/?ordering=created_by__password").status_code, 200
        )
        page = self.client.get("/api/deliveries/?page_size=100000")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.data["page_size"], 200)

    def test_expense_type_in_use_cannot_be_deleted(self):
        delivery = self.create_delivery()
        expense = self.add_expense(delivery)
        self.auth(self.admin)
        response = self.client.delete(f"/api/expense-types/{expense.expense_type_id}/")
        self.assertEqual(response.status_code, 400)

    def test_last_admin_cannot_be_removed_or_blocked(self):
        self.auth(self.admin)
        self.assertEqual(self.client.delete(f"/api/users/{self.admin.id}/").status_code, 400)
        self.assertEqual(
            self.client.post(
                f"/api/users/{self.admin.id}/set-active/", {"is_active": False}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/users/{self.admin.id}/", {"role": "EMPLOYEE"}, format="json"
            ).status_code,
            400,
        )

    def test_empty_export_returns_header_only(self):
        self.auth(self.admin)
        response = self.client.get("/api/reports/export/deliveries/?ext=csv")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8-sig").strip()
        self.assertEqual(len(body.splitlines()), 1)
        self.assertTrue(body.startswith("ID;Машина"))

    def test_expense_totals_are_split_by_currency(self):
        delivery = self.create_delivery()
        for amount, currency in (("10", Currency.USD), ("20", Currency.USD), ("300", Currency.KGS)):
            ExpenseService().add_expense(
                actor=self.employee,
                delivery=delivery,
                data={
                    "expense_type_id": ExpenseType.objects.first().id,
                    "amount": Decimal(amount),
                    "currency": currency,
                    "description": "Смешение валют",
                },
            )
        self.auth(self.employee)
        response = self.client.get(f"/api/deliveries/{delivery.id}/")
        self.assertEqual(response.data["expense_totals"], {"KGS": "300.00", "USD": "30.00"})

    def test_has_expenses_filter_does_not_duplicate_rows(self):
        delivery = self.create_delivery()
        self.add_expense(delivery, "10")
        self.add_expense(delivery, "20")
        self.create_delivery(vehicle_number="02 KG 0000 AA")

        self.auth(self.employee)
        response = self.client.get("/api/deliveries/?has_expenses=true")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["expenses_count"], 2)

    def test_reports_group_deliveries_correctly(self):
        """Проверка гипотезы о «протекающих» аннотациях: отчёты считают верно."""
        from apps.deliveries.repositories import DeliveryRepository
        from apps.reports.services import ReportService

        first = self.create_delivery()
        self.create_delivery()
        self.add_expense(first)

        rows = ReportService().by_employee(DeliveryRepository().get_queryset())
        by_id = {row["user_id"]: row for row in rows}
        self.assertEqual(by_id[self.employee.id]["dispatched"], 2)

        routes = ReportService().by_route(DeliveryRepository().get_queryset())
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]["count"], 2)
