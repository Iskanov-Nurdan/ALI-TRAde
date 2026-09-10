# -*- coding: utf-8 -*-
"""Атака на очистку пользовательского текста.

apps/core/validators.py объявляет, что «разметка в комментариях и описаниях не
нужна, а её хранение делает уязвимым любого стороннего потребителя API».
Тесты ниже показывают, что это правило обходится и что часть полей вообще не
проходит через plain_text.
"""
from apps.accounts.models import User
from apps.deliveries.models import Delivery, DeliveryEvent
from apps.points.models import Point

from .base import AdversarialBase

# Управляющий символ \x01 входит в CONTROL_CHARS и вырезается ПОСЛЕ проверки
# на HTML, поэтому проверка тега не срабатывает, а тег собирается обратно.
SMUGGLED = "<\x01script>alert(document.cookie)</\x01script>"
PLAIN_HTML = "<script>alert(1)</script>"


class ControlCharacterBypass(AdversarialBase):
    """Управляющий символ внутри тега обходит фильтр HTML."""

    def test_comment_must_not_store_reassembled_script_tag(self):
        """В комментарий рейса нельзя протащить рабочий <script>.

        HTML_TAG.search выполняется до CONTROL_CHARS.sub, поэтому строка
        "<\\x01script>" проверку проходит, а после очистки превращается
        в настоящий "<script>".
        """
        delivery = self.make_delivery()
        self.auth(self.employee)

        response = self.client.post(
            f"/api/deliveries/{delivery.id}/comments/",
            {"comment": SMUGGLED},
            format="json",
        )

        stored = DeliveryEvent.objects.filter(
            event_type=DeliveryEvent.EventType.COMMENT_ADDED
        ).values_list("comment", flat=True).first()
        self.assertNotIn(
            "<script>",
            stored or "",
            f"в базе оказался рабочий тег: {stored!r} (ответ {response.status_code})",
        )

    def test_point_name_must_not_store_reassembled_script_tag(self):
        """То же самое в названии точки — оно выводится во всех списках рейсов."""
        self.auth(self.admin)

        response = self.client.post(
            "/api/points/", {"name": SMUGGLED}, format="json"
        )

        names = list(Point.objects.values_list("name", flat=True))
        self.assertFalse(
            any("<script>" in name for name in names),
            f"в справочнике точек рабочий тег: {names} (ответ {response.status_code})",
        )

    def test_expense_description_must_not_store_reassembled_script_tag(self):
        """Описание расхода попадает в отчёты и выгрузки — тег недопустим."""
        delivery = self.make_delivery()
        self.auth(self.employee)

        self.client.post(
            "/api/expenses/",
            {
                "delivery": delivery.id,
                "expense_type_id": self.expense_type.id,
                "amount": "10.00",
                "currency": "USD",
                "description": SMUGGLED,
            },
            format="json",
        )

        from apps.expenses.models import Expense

        stored = list(Expense.objects.values_list("description", flat=True))
        self.assertFalse(
            any("<script>" in item for item in stored),
            f"в расходах рабочий тег: {stored}",
        )


class UnvalidatedTextFields(AdversarialBase):
    """Поля, которые вообще не проходят через plain_text."""

    def test_vehicle_number_must_reject_markup(self):
        """Номер машины показывается в каждом списке и в выгрузке.

        Проверок на разметку у него нет: normalize_vehicle_number выкидывает
        скобки только для поискового поля, а vehicle_number сохраняется как есть.
        """
        self.auth(self.employee)

        response = self.client.post(
            "/api/deliveries/",
            {
                "point_from_id": self.point_from.id,
                "point_to_id": self.point_to.id,
                "vehicle_number": "<IMG SRC=X ONERROR=1>",
                "duration_hours": "4",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            400,
            f"номер с разметкой принят: {list(Delivery.objects.values_list('vehicle_number', flat=True))}",
        )

    def test_employee_full_name_must_reject_markup(self):
        """ФИО сотрудника отдаётся во всех вложенных объектах (created_by и др.)."""
        self.auth(self.admin)

        response = self.client.post(
            "/api/users/",
            {
                "full_name": PLAIN_HTML,
                "login": "attacker",
                "password": "verysecret99",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            400,
            f"ФИО с разметкой принято: {list(User.objects.values_list('full_name', flat=True))}",
        )

    def test_point_address_and_phone_must_reject_markup(self):
        """У точки очищаются только name и description, address и phone — нет."""
        self.auth(self.admin)

        response = self.client.post(
            "/api/points/",
            {
                "name": "Склад на въезде",
                "address": PLAIN_HTML,
                "phone": "<b>+996</b>",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            400,
            "адрес и телефон точки приняты с разметкой: "
            f"{list(Point.objects.values_list('address', 'phone'))}",
        )


class PointNameLengthRule(AdversarialBase):
    """Правило минимальной длины названия точки действует только при создании."""

    def test_point_name_min_length_also_applies_on_update(self):
        """PointWriteSerializer требует >= 2 символов, PointUpdateSerializer — нет.

        Значит правило обходится редактированием уже созданной точки.
        """
        self.auth(self.admin)
        created = self.client.post("/api/points/", {"name": "."}, format="json")
        self.assertEqual(created.status_code, 400, "создание точки с именем '.' должно отклоняться")

        response = self.client.patch(
            f"/api/points/{self.point_from.id}/", {"name": "."}, format="json"
        )

        self.assertEqual(
            response.status_code,
            400,
            f"через PATCH имя точки стало {Point.objects.get(pk=self.point_from.id).name!r}",
        )
