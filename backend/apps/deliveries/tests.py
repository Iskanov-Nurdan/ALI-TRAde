"""Тесты ключевых бизнес-правил: дедлайн, просрочка, приём, история."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User, UserRole
from apps.core.exceptions import BusinessError
from apps.deliveries.models import DeliveryEvent, DeliveryStatus, normalize_vehicle_number
from apps.deliveries.services import DeliveryService
from apps.expenses.models import Currency, Expense, ExpenseSettings, ExpenseType, Payer
from apps.expenses.services import ExpenseService
from apps.points.models import Point


def make_user(login="worker", role=UserRole.EMPLOYEE):
    return User.objects.create_user(login=login, password="secret12345", full_name=f"Сотрудник {login}", role=role)


class DeliveryServiceTests(TestCase):
    def setUp(self):
        self.employee = make_user("employee1")
        self.other = make_user("employee2")
        self.bishkek = Point.objects.create(name="Бишкек")
        self.dostuk = Point.objects.create(name="Достук")
        self.service = DeliveryService()

    def _create(self, **overrides):
        data = {
            "point_from_id": self.bishkek.id,
            "point_to_id": self.dostuk.id,
            "vehicle_number": "1234 ABC",
            "dispatched_at": timezone.now(),
            "duration_hours": Decimal("4"),
            "auto_dispatch": True,
        }
        data.update(overrides)
        return self.service.create_delivery(actor=self.employee, data=data)

    def test_deadline_calculated_from_duration(self):
        dispatched_at = timezone.now()
        delivery = self._create(dispatched_at=dispatched_at)
        self.assertEqual(delivery.deadline_at, dispatched_at + timedelta(hours=4))
        self.assertEqual(delivery.planned_duration_minutes, 240)
        self.assertEqual(delivery.status, DeliveryStatus.IN_TRANSIT)

    def test_deadline_can_be_exact_time(self):
        dispatched_at = timezone.now()
        deadline = dispatched_at + timedelta(hours=2, minutes=30)
        delivery = self._create(dispatched_at=dispatched_at, duration_hours=None, deadline_at=deadline)
        self.assertEqual(delivery.deadline_at, deadline)
        self.assertEqual(delivery.planned_duration_minutes, 150)

    def test_deadline_required(self):
        with self.assertRaises(BusinessError):
            self._create(duration_hours=None, duration_minutes=None)

    def test_same_points_rejected(self):
        with self.assertRaises(BusinessError):
            self._create(point_to_id=self.bishkek.id)

    def test_inactive_point_rejected(self):
        self.dostuk.is_active = False
        self.dostuk.save()
        with self.assertRaises(BusinessError):
            self._create()

    def test_overdue_detected_automatically(self):
        delivery = self._create(dispatched_at=timezone.now() - timedelta(hours=6))
        self.assertTrue(delivery.is_overdue)
        self.assertGreater(delivery.late_minutes, 0)
        self.assertEqual(delivery.color(has_expenses=False), "RED")

    def test_expense_makes_row_orange_but_red_wins(self):
        on_time = self._create()
        self.assertEqual(on_time.color(has_expenses=True), "ORANGE")

        overdue = self._create(dispatched_at=timezone.now() - timedelta(hours=6))
        self.assertEqual(overdue.color(has_expenses=True), "RED")

    def test_receive_calculates_late_minutes_and_keeps_overdue_history(self):
        dispatched_at = timezone.now() - timedelta(hours=4, minutes=27)
        delivery = self._create(dispatched_at=dispatched_at)
        received = self.service.receive(actor=self.other, delivery=delivery, data={})

        self.assertEqual(received.status, DeliveryStatus.ARRIVED)
        self.assertEqual(received.received_by, self.other)
        self.assertTrue(received.arrived_late)
        self.assertEqual(received.late_minutes, 27)

        event_types = list(received.events.values_list("event_type", flat=True))
        self.assertIn(DeliveryEvent.EventType.DEADLINE_PASSED, event_types)
        self.assertIn(DeliveryEvent.EventType.RECEIVED, event_types)

    def test_receive_twice_rejected(self):
        delivery = self._create()
        self.service.receive(actor=self.other, delivery=delivery, data={})
        with self.assertRaises(BusinessError):
            self.service.receive(actor=self.other, delivery=delivery, data={})

    def test_receive_requires_dispatch(self):
        delivery = self._create(auto_dispatch=False)
        self.assertEqual(delivery.status, DeliveryStatus.CREATED)
        with self.assertRaises(BusinessError):
            self.service.receive(actor=self.other, delivery=delivery, data={})

    def test_dispatch_recalculates_deadline_from_actual_time(self):
        delivery = self._create(auto_dispatch=False, dispatched_at=timezone.now() - timedelta(hours=3))
        actual = timezone.now()
        dispatched = self.service.dispatch(actor=self.other, delivery=delivery, data={"dispatched_at": actual})
        self.assertEqual(dispatched.deadline_at, actual + timedelta(hours=4))
        self.assertEqual(dispatched.dispatched_by, self.other)

    def test_sync_overdue_events_is_idempotent(self):
        self._create(dispatched_at=timezone.now() - timedelta(hours=6))
        self.assertEqual(self.service.sync_overdue_events(), 1)
        self.assertEqual(self.service.sync_overdue_events(), 0)

    def test_cancel_requires_reason(self):
        delivery = self._create()
        with self.assertRaises(BusinessError):
            self.service.cancel(actor=self.employee, delivery=delivery, data={"comment": ""})

    def test_vehicle_number_normalization(self):
        self.assertEqual(normalize_vehicle_number("01 KG 1234 AB"), "01KG1234AB")
        delivery = self._create(vehicle_number="01 kg 1234 ab")
        self.assertEqual(delivery.vehicle_number, "01 KG 1234 AB")
        self.assertEqual(delivery.vehicle_number_search, "01KG1234AB")


class DeliveryWaypointTests(TestCase):
    """Маршрут из нескольких точек: Бишкек → граница → Достук."""

    def setUp(self):
        self.employee = make_user("waypoint1")
        self.other = make_user("waypoint2")
        self.bishkek = Point.objects.create(name="Бишкек")
        self.border = Point.objects.create(name="Граница")
        self.warehouse = Point.objects.create(name="Склад")
        self.dostuk = Point.objects.create(name="Достук")
        self.service = DeliveryService()

    def _create(self, waypoint_ids=None, **overrides):
        data = {
            "point_from_id": self.bishkek.id,
            "point_to_id": self.dostuk.id,
            "vehicle_number": "1234 ABC",
            "duration_hours": Decimal("8"),
            "waypoint_ids": waypoint_ids if waypoint_ids is not None else [self.border.id],
        }
        data.update(overrides)
        return self.service.create_delivery(actor=self.employee, data=data)

    def test_route_keeps_order_of_waypoints(self):
        delivery = self._create([self.border.id, self.warehouse.id])
        self.assertEqual(delivery.route_points, ["Бишкек", "Граница", "Склад", "Достук"])
        self.assertEqual([w.order for w in delivery.waypoints.all()], [1, 2])

    def test_waypoint_cannot_duplicate_route_ends(self):
        with self.assertRaises(BusinessError):
            self._create([self.bishkek.id])
        with self.assertRaises(BusinessError):
            self._create([self.dostuk.id])

    def test_waypoints_cannot_repeat(self):
        with self.assertRaises(BusinessError):
            self._create([self.border.id, self.border.id])

    def test_inactive_waypoint_rejected(self):
        self.border.is_active = False
        self.border.save()
        with self.assertRaises(BusinessError):
            self._create([self.border.id])

    def test_pass_waypoint_records_employee_and_event(self):
        delivery = self._create([self.border.id])
        waypoint = delivery.waypoints.first()

        passed = self.service.pass_waypoint(
            actor=self.other, delivery=delivery, waypoint=waypoint, data={}
        )
        self.assertTrue(passed.is_passed)
        self.assertEqual(passed.passed_by, self.other)

        events = delivery.events.filter(event_type=DeliveryEvent.EventType.WAYPOINT_PASSED)
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().metadata["point"], "Граница")

    def test_waypoint_cannot_be_passed_twice(self):
        delivery = self._create([self.border.id])
        waypoint = delivery.waypoints.first()
        self.service.pass_waypoint(actor=self.other, delivery=delivery, waypoint=waypoint, data={})
        with self.assertRaises(BusinessError):
            self.service.pass_waypoint(actor=self.employee, delivery=delivery, waypoint=waypoint, data={})

    def test_waypoint_requires_dispatched_delivery(self):
        delivery = self._create([self.border.id], auto_dispatch=False)
        waypoint = delivery.waypoints.first()
        with self.assertRaises(BusinessError):
            self.service.pass_waypoint(actor=self.other, delivery=delivery, waypoint=waypoint, data={})

    def test_passed_waypoint_cannot_be_removed_on_update(self):
        delivery = self._create([self.border.id, self.warehouse.id])
        waypoint = delivery.waypoints.first()
        self.service.pass_waypoint(actor=self.other, delivery=delivery, waypoint=waypoint, data={})

        with self.assertRaises(BusinessError):
            self.service.update_delivery(
                actor=self.employee, delivery=delivery, data={"waypoint_ids": [self.warehouse.id]}
            )

    def test_update_replaces_unpassed_waypoints(self):
        delivery = self._create([self.border.id])
        self.service.update_delivery(
            actor=self.employee, delivery=delivery, data={"waypoint_ids": [self.warehouse.id]}
        )
        delivery.refresh_from_db()
        self.assertEqual(delivery.route_points, ["Бишкек", "Склад", "Достук"])

    def test_api_creates_and_passes_waypoint(self):
        client = APIClient()
        response = client.post(
            "/api/auth/login/", {"login": self.employee.login, "password": "secret12345"}, format="json"
        )
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")

        created = client.post(
            "/api/deliveries/",
            {
                "point_from_id": self.bishkek.id,
                "point_to_id": self.dostuk.id,
                "vehicle_number": "1234 ABC",
                "duration_hours": "8",
                "waypoint_ids": [self.border.id, self.warehouse.id],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["route_points"], ["Бишкек", "Граница", "Склад", "Достук"])

        delivery_id = created.data["id"]
        waypoint_id = created.data["waypoints"][0]["id"]
        passed = client.post(
            f"/api/deliveries/{delivery_id}/waypoints/{waypoint_id}/pass/", {}, format="json"
        )
        self.assertEqual(passed.status_code, 200)
        self.assertTrue(passed.data["waypoints"][0]["is_passed"])
        self.assertFalse(passed.data["waypoints"][1]["is_passed"])


class ExpenseServiceTests(TestCase):
    def setUp(self):
        self.employee = make_user("employee3")
        self.second = make_user("employee5")
        self.point_a = Point.objects.create(name="Бишкек")
        self.point_b = Point.objects.create(name="Достук")
        # Типы расходов создаются миграцией — берём готовые.
        self.tax = ExpenseType.objects.get(code="tax")
        self.axle = ExpenseType.objects.get(code="axle-fine")
        self.delivery = DeliveryService().create_delivery(
            actor=self.employee,
            data={
                "point_from_id": self.point_a.id,
                "point_to_id": self.point_b.id,
                "vehicle_number": "1234 ABC",
                "duration_hours": Decimal("4"),
            },
        )
        self.service = ExpenseService()

    def _add(self, actor, expense_type, amount, **extra):
        data = {
            "expense_type_id": expense_type.id,
            "amount": Decimal(amount),
            "currency": Currency.USD,
            "description": "Платёж на границе",
        }
        data.update(extra)
        return self.service.add_expense(actor=actor, delivery=self.delivery, data=data)

    def test_multiple_employees_add_expenses_to_one_delivery(self):
        self._add(self.employee, self.tax, "30")
        self._add(self.second, self.axle, "100")

        expenses = Expense.objects.filter(delivery=self.delivery)
        self.assertEqual(expenses.count(), 2)
        self.assertEqual(sum(item.amount for item in expenses), Decimal("130"))
        self.assertEqual({item.created_by_id for item in expenses}, {self.employee.id, self.second.id})

    def test_expense_can_be_added_after_arrival(self):
        DeliveryService().receive(actor=self.second, delivery=self.delivery, data={})
        self.delivery.refresh_from_db()
        expense = self._add(self.employee, self.tax, "30")
        self.assertEqual(expense.delivery_id, self.delivery.id)

    def test_expense_logged_in_history(self):
        self._add(self.employee, self.axle, "100")
        events = self.delivery.events.filter(event_type=DeliveryEvent.EventType.EXPENSE_ADDED)
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().metadata["amount"], "100")

    def test_payer_rule_applied_when_not_selected(self):
        settings = ExpenseSettings.load()
        settings.auto_payer_enabled = True
        settings.threshold_amount = Decimal("50")
        settings.threshold_currency = Currency.USD
        settings.payer_above = Payer.CHINA
        settings.payer_below = Payer.COMPANY
        settings.save()

        big = self._add(self.employee, self.axle, "100")
        small = self._add(self.employee, self.tax, "30")

        self.assertEqual(big.payer, Payer.CHINA)
        self.assertTrue(big.payer_auto_assigned)
        self.assertEqual(small.payer, Payer.COMPANY)

    def test_manual_payer_wins_over_rule(self):
        settings = ExpenseSettings.load()
        settings.auto_payer_enabled = True
        settings.save()

        expense = self._add(self.employee, self.axle, "100", payer=Payer.DRIVER)
        self.assertEqual(expense.payer, Payer.DRIVER)
        self.assertFalse(expense.payer_auto_assigned)


class ApiPermissionTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin1", role=UserRole.ADMIN)
        self.employee = make_user("employee9")
        self.point = Point.objects.create(name="Бишкек")
        self.client = APIClient()

    def _auth(self, user):
        response = self.client.post(
            "/api/auth/login/", {"login": user.login, "password": "secret12345"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")

    def test_anonymous_denied(self):
        self.assertEqual(self.client.get("/api/deliveries/").status_code, 401)

    def test_employee_cannot_manage_points_or_users(self):
        self._auth(self.employee)
        self.assertEqual(self.client.post("/api/points/", {"name": "Ош"}, format="json").status_code, 403)
        self.assertEqual(self.client.get("/api/users/").status_code, 403)
        self.assertEqual(self.client.get("/api/reports/summary/").status_code, 403)

    def test_employee_can_read_points_and_create_delivery(self):
        self._auth(self.employee)
        self.assertEqual(self.client.get("/api/points/").status_code, 200)

        other = Point.objects.create(name="Достук")
        response = self.client.post(
            "/api/deliveries/",
            {
                "point_from_id": self.point.id,
                "point_to_id": other.id,
                "vehicle_number": "1234 ABC",
                "duration_hours": "4",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "IN_TRANSIT")

    def test_admin_manages_users(self):
        self._auth(self.admin)
        response = self.client.post(
            "/api/users/",
            {"full_name": "Новый Сотрудник", "login": "newbie", "password": "secret12345"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        user_id = response.data["id"]
        blocked = self.client.post(f"/api/users/{user_id}/set-active/", {"is_active": False}, format="json")
        self.assertEqual(blocked.status_code, 200)
        self.assertFalse(blocked.data["is_active"])

    def test_blocked_user_cannot_login(self):
        self.employee.is_active = False
        self.employee.save()
        response = self.client.post(
            "/api/auth/login/", {"login": self.employee.login, "password": "secret12345"}, format="json"
        )
        self.assertEqual(response.status_code, 401)

    def test_vehicle_search_finds_deliveries(self):
        other = Point.objects.create(name="Достук")
        DeliveryService().create_delivery(
            actor=self.employee,
            data={
                "point_from_id": self.point.id,
                "point_to_id": other.id,
                "vehicle_number": "01 KG 1234 AB",
                "duration_hours": Decimal("4"),
            },
        )
        self._auth(self.employee)
        response = self.client.get("/api/vehicles/search/?q=1234")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["vehicles"][0]["vehicle_number"], "01 KG 1234 AB")

    def test_admin_cannot_delete_last_admin(self):
        self._auth(self.admin)
        response = self.client.delete(f"/api/users/{self.admin.id}/")
        self.assertEqual(response.status_code, 400)
