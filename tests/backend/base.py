# -*- coding: utf-8 -*-
"""Общая обвязка адверсариальных тестов.

Ничего из backend/** не изменяется: тесты работают только через публичный API
и сервисный слой.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User, UserRole
from apps.deliveries.models import Delivery, DeliveryStatus
from apps.expenses.models import ExpenseType
from apps.points.models import Point

PASSWORD = "secret12345"


class AdversarialBase(TestCase):
    """Минимальный набор данных: два сотрудника, три точки, тип расхода."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            login="admin", password=PASSWORD, full_name="Админ Админов", role=UserRole.ADMIN
        )
        self.employee = User.objects.create_user(
            login="worker", password=PASSWORD, full_name="Иван Иванов"
        )
        self.point_from = Point.objects.create(name="Бишкек")
        self.point_to = Point.objects.create(name="Ош")
        self.border = Point.objects.create(name="Граница Торугарт")
        self.expense_type = ExpenseType.objects.create(code="fuel", name="Топливо")

    # --- вспомогательное ---

    def auth(self, user):
        self.client.force_authenticate(user=user)

    def login(self, login=None, password=PASSWORD, client=None):
        """Настоящий вход через API — возвращает ответ с access/refresh."""
        client = client or APIClient()
        return client.post(
            "/api/auth/login/",
            {"login": login or self.employee.login, "password": password},
            format="json",
        )

    def make_delivery(self, *, actor=None, number="01KG1234AB", hours_ago=4, deadline_in=5, **kw):
        """Рейс в пути, создан напрямую в БД (сервисный слой тестируется отдельно)."""
        actor = actor or self.employee
        now = timezone.now()
        params = dict(
            point_from=self.point_from,
            point_to=self.point_to,
            vehicle_number=number,
            created_by=actor,
            dispatched_by=actor,
            dispatched_at=now - timedelta(hours=hours_ago),
            deadline_at=now + timedelta(hours=deadline_in),
            status=DeliveryStatus.IN_TRANSIT,
        )
        params.update(kw)
        return Delivery.objects.create(**params)
