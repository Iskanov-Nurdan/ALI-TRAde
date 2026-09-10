from decimal import Decimal

from rest_framework import serializers

from apps.accounts.serializers import UserShortSerializer
from apps.core.validators import plain_text
from apps.expenses.models import Currency, CurrencyRate, Expense, ExpenseSettings, ExpenseType, Payer


class ExpenseTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseType
        fields = ("id", "code", "name", "sort_order", "is_active")
        read_only_fields = fields


class ExpenseTypeWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    code = serializers.SlugField(max_length=40, required=False)
    sort_order = serializers.IntegerField(min_value=0, max_value=32000, required=False, default=100)
    is_active = serializers.BooleanField(required=False, default=True)

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Название типа расхода слишком короткое.")
        return value


class ExpenseSerializer(serializers.ModelSerializer):
    expense_type_name = serializers.CharField(source="expense_type.name", read_only=True)
    payer_display = serializers.CharField(source="get_payer_display", read_only=True)
    created_by = UserShortSerializer(read_only=True)
    delivery_vehicle = serializers.CharField(source="delivery.vehicle_number", read_only=True)

    class Meta:
        model = Expense
        fields = (
            "id",
            "delivery",
            "delivery_vehicle",
            "expense_type",
            "expense_type_name",
            "amount",
            "currency",
            "payer",
            "payer_display",
            "payer_auto_assigned",
            "description",
            "comment",
            "created_by",
            "created_at",
        )
        read_only_fields = fields


class ExpenseCreateSerializer(serializers.Serializer):
    expense_type_id = serializers.IntegerField()
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )
    currency = serializers.ChoiceField(choices=Currency.choices, default=Currency.USD)
    payer = serializers.ChoiceField(choices=Payer.choices, required=False, allow_blank=True)
    description = serializers.CharField(max_length=255)
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")

    def validate_description(self, value: str) -> str:
        value = plain_text(value).strip()
        if len(value) < 2:
            raise serializers.ValidationError("Опишите расход подробнее.")
        return value

    def validate_comment(self, value: str) -> str:
        return plain_text(value)


class ExpenseUpdateSerializer(serializers.Serializer):
    expense_type_id = serializers.IntegerField(required=False)
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01"), required=False
    )
    currency = serializers.ChoiceField(choices=Currency.choices, required=False)
    payer = serializers.ChoiceField(choices=Payer.choices, required=False)
    description = serializers.CharField(max_length=255, required=False)
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True)

    def validate_description(self, value: str) -> str:
        return plain_text(value).strip()

    def validate_comment(self, value: str) -> str:
        return plain_text(value)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Не переданы поля для изменения.")
        return attrs


class ExpenseSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseSettings
        fields = (
            "auto_payer_enabled",
            "threshold_amount",
            "threshold_currency",
            "payer_above",
            "payer_below",
            "updated_at",
        )
        read_only_fields = ("updated_at",)


class ExpenseSettingsWriteSerializer(serializers.Serializer):
    auto_payer_enabled = serializers.BooleanField(required=False)
    threshold_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False
    )
    threshold_currency = serializers.ChoiceField(choices=Currency.choices, required=False)
    payer_above = serializers.ChoiceField(choices=Payer.choices, required=False)
    payer_below = serializers.ChoiceField(choices=Payer.choices, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Не переданы поля для изменения.")
        return attrs


class CurrencyRateSerializer(serializers.ModelSerializer):
    """Курс валюты к сому."""

    currency_display = serializers.CharField(source="get_code_display", read_only=True)
    is_base = serializers.BooleanField(read_only=True)
    updated_by = UserShortSerializer(read_only=True)

    class Meta:
        model = CurrencyRate
        fields = ("code", "currency_display", "rate", "is_base", "updated_by", "updated_at")
        read_only_fields = fields


class CurrencyRateWriteSerializer(serializers.Serializer):
    """Обновление курсов: {"rates": {"USD": "89.40"}}."""

    rates = serializers.DictField(
        child=serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0.0001"))
    )

    def validate_rates(self, value):
        if not value:
            raise serializers.ValidationError("Не переданы курсы для сохранения.")
        allowed = set(Currency.values)
        unknown = set(value) - allowed
        if unknown:
            raise serializers.ValidationError(f"Неизвестные валюты: {', '.join(sorted(unknown))}.")
        return value
