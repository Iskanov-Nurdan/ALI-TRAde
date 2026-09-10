# -*- coding: utf-8 -*-
"""Атака на доменные правила: просрочка, хронология рейса, плательщик."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.core.utils import humanize_minutes
from apps.deliveries.models import Delivery, DeliveryEvent
from apps.deliveries.services import DeliveryService
from apps.expenses.models import ExpenseSettings

from .base import AdversarialBase


class OverdueAfterDeadlineExtension(AdversarialBase):
    """Продление срока навсегда выключает фиксацию просрочки."""

    def test_second_overdue_is_logged_after_deadline_was_extended(self):
        """Рейс просрочен второй раз — история об этом молчит.

        Сценарий: рейс просрочен, событие DEADLINE_PASSED записано,
        deadline_passed_logged=True. Администратор продлевает срок — флаг не
        снимается, потому что событие уже есть (services.py:428-435).
        Новый срок тоже проходит, но unlogged_overdue() рейс уже не видит:
        в истории нет ни одной записи о второй просрочке, хотя is_overdue=True.
        """
        now = timezone.now()
        delivery = self.make_delivery(deadline_at=now - timedelta(hours=1))
        DeliveryService().sync_overdue_events()
        delivery.refresh_from_db()
        self.assertTrue(delivery.deadline_passed_logged)
        self.assertEqual(delivery.events.filter(event_type="DEADLINE_PASSED").count(), 1)

        self.auth(self.admin)
        extended = self.client.patch(
            f"/api/deliveries/{delivery.id}/",
            {"deadline_at": (now + timedelta(hours=1)).isoformat()},
            format="json",
        )
        self.assertEqual(extended.status_code, 200)

        # Продлённый срок тоже истёк.
        Delivery.objects.filter(pk=delivery.pk).update(deadline_at=now - timedelta(minutes=5))
        DeliveryService().sync_overdue_events()
        delivery.refresh_from_db()

        self.assertTrue(delivery.is_overdue, "рейс обязан считаться просроченным")
        self.assertEqual(
            delivery.events.filter(event_type="DEADLINE_PASSED").count(),
            2,
            "вторая просрочка (по новому сроку) не попала в историю рейса",
        )


class DeliveryTimelineConsistency(AdversarialBase):
    """Хронология рейса не проверяется относительно промежуточных точек."""

    def _delivery_with_waypoint(self, number):
        self.auth(self.employee)
        response = self.client.post(
            "/api/deliveries/",
            {
                "point_from_id": self.point_from.id,
                "point_to_id": self.point_to.id,
                "vehicle_number": number,
                "duration_hours": "10",
                "waypoint_ids": [self.border.id],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        delivery_id = response.data["id"]
        # Отодвигаем отправление в прошлое, чтобы работать с реальными датами.
        Delivery.objects.filter(pk=delivery_id).update(
            dispatched_at=timezone.now() - timedelta(hours=6)
        )
        delivery = Delivery.objects.get(pk=delivery_id)
        return delivery, delivery.waypoints.first()

    def test_arrival_cannot_precede_a_passed_waypoint(self):
        """Рейс «прибыл» раньше, чем прошёл промежуточную точку.

        pass_waypoint проверяет только passed_at >= dispatched_at, а receive
        сверяет received_at только с dispatched_at. В итоге получается маршрут,
        где машина оказалась в конечной точке за 4 часа до границы.
        """
        delivery, waypoint = self._delivery_with_waypoint("01KG5555AB")
        passed_at = timezone.now() - timedelta(hours=1)
        passed = self.client.post(
            f"/api/deliveries/{delivery.id}/waypoints/{waypoint.id}/pass/",
            {"passed_at": passed_at.isoformat()},
            format="json",
        )
        self.assertEqual(passed.status_code, 200, passed.data)

        response = self.client.post(
            f"/api/deliveries/{delivery.id}/receive/",
            {"received_at": (timezone.now() - timedelta(hours=5)).isoformat()},
            format="json",
        )

        delivery.refresh_from_db()
        waypoint.refresh_from_db()
        self.assertEqual(
            response.status_code,
            400,
            "прибытие раньше пройденной точки принято: "
            f"received_at={delivery.received_at}, passed_at={waypoint.passed_at}",
        )

    def test_dispatch_time_cannot_be_moved_after_a_passed_waypoint(self):
        """Правка отправления делает пройденную точку «пройденной до выезда».

        update_delivery сверяет dispatched_at только с deadline_at и received_at,
        промежуточные точки в проверку не входят (services.py:421-424).
        """
        delivery, waypoint = self._delivery_with_waypoint("01KG7777AB")
        self.client.post(
            f"/api/deliveries/{delivery.id}/waypoints/{waypoint.id}/pass/",
            {"passed_at": (timezone.now() - timedelta(hours=5)).isoformat()},
            format="json",
        )

        self.auth(self.admin)
        response = self.client.patch(
            f"/api/deliveries/{delivery.id}/",
            {"dispatched_at": (timezone.now() - timedelta(hours=1)).isoformat()},
            format="json",
        )

        delivery.refresh_from_db()
        waypoint.refresh_from_db()
        self.assertEqual(
            response.status_code,
            400,
            "отправление сдвинуто на момент позже прохождения точки: "
            f"dispatched_at={delivery.dispatched_at}, passed_at={waypoint.passed_at}",
        )


class LateMinutesRounding(AdversarialBase):
    """Опоздание меньше минуты: признак есть, величины нет."""

    def test_sub_minute_delay_is_reported_consistently(self):
        """arrived_late=True при late_minutes=0 и пустой колонке в выгрузке.

        late_minutes режет секунды через // 60, а arrived_late сравнивает
        строго. Рейс помечается как «Прибыл с опозданием», но в отчёте по
        сотрудникам и в колонке «Опоздание» стоит пусто — величину опоздания
        нельзя ни увидеть, ни просуммировать.
        """
        now = timezone.now()
        delivery = self.make_delivery(deadline_at=now - timedelta(seconds=30))
        self.auth(self.employee)

        response = self.client.post(f"/api/deliveries/{delivery.id}/receive/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

        self.assertTrue(response.data["arrived_late"])
        self.assertNotEqual(
            (response.data["late_minutes"], humanize_minutes(response.data["late_minutes"])),
            (0, ""),
            "рейс помечен опоздавшим, но величина опоздания равна нулю и в выгрузке пуста",
        )


class AutoPayerConsistency(AdversarialBase):
    """Правило плательщика не пересчитывается при изменении суммы."""

    def test_auto_assigned_payer_is_recalculated_when_amount_changes(self):
        """Расход помечен «плательщик определён правилом», но правилу не соответствует.

        Порог 50 USD: 100 USD -> CHINA (payer_auto_assigned=True). Админ правит
        сумму на 1 USD — плательщик остаётся CHINA, а флаг «определён правилом»
        остаётся True. Отчёт «по плательщикам» считает такой расход китайским.
        """
        settings_obj = ExpenseSettings.load()
        settings_obj.auto_payer_enabled = True
        settings_obj.threshold_amount = Decimal("50")
        settings_obj.threshold_currency = "USD"
        settings_obj.payer_above = "CHINA"
        settings_obj.payer_below = "COMPANY"
        settings_obj.save()

        delivery = self.make_delivery()
        self.auth(self.employee)
        created = self.client.post(
            "/api/expenses/",
            {
                "delivery": delivery.id,
                "expense_type_id": self.expense_type.id,
                "amount": "100.00",
                "currency": "USD",
                "description": "перегруз",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["payer"], "CHINA")
        self.assertTrue(created.data["payer_auto_assigned"])

        self.auth(self.admin)
        updated = self.client.patch(
            f"/api/expenses/{created.data['id']}/", {"amount": "1.00"}, format="json"
        )
        self.assertEqual(updated.status_code, 200, updated.data)

        self.assertFalse(
            updated.data["payer_auto_assigned"] and updated.data["payer"] == "CHINA",
            "сумма 1 USD ниже порога 50 USD, но расход по-прежнему помечен "
            "как автоматически отнесённый на Китай",
        )
