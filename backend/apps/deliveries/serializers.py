from collections import defaultdict
from decimal import Decimal

from rest_framework import serializers

from apps.accounts.serializers import UserShortSerializer
from apps.core.validators import plain_text
from apps.deliveries.models import (
    Delivery,
    DeliveryEvent,
    DeliveryStatus,
    DeliveryWaypoint,
    normalize_vehicle_number,
)
from apps.expenses.serializers import ExpenseSerializer
from apps.points.serializers import PointShortSerializer


class DeliveryEventSerializer(serializers.ModelSerializer):
    user = UserShortSerializer(read_only=True)
    event_type_display = serializers.CharField(source="get_event_type_display", read_only=True)

    class Meta:
        model = DeliveryEvent
        fields = (
            "id",
            "delivery",
            "event_type",
            "event_type_display",
            "user",
            "event_time",
            "comment",
            "metadata",
        )
        read_only_fields = fields


class DeliveryWaypointSerializer(serializers.ModelSerializer):
    """Промежуточная точка маршрута с отметкой прохождения."""

    point = PointShortSerializer(read_only=True)
    passed_by = UserShortSerializer(read_only=True)
    is_passed = serializers.BooleanField(read_only=True)

    class Meta:
        model = DeliveryWaypoint
        fields = ("id", "point", "order", "passed_at", "passed_by", "is_passed", "comment")
        read_only_fields = fields


class PassWaypointSerializer(serializers.Serializer):
    passed_at = serializers.DateTimeField(required=False, allow_null=True)
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")

    def validate_comment(self, value: str) -> str:
        return plain_text(value)


class DeliveryTotalsMixin:
    """Суммы расходов по валютам: из контекста списка либо из связанных объектов."""

    def get_expense_totals(self, obj: Delivery) -> dict:
        totals_map = self.context.get("expense_totals")
        if totals_map is not None:
            totals = totals_map.get(obj.id, {})
        else:
            totals = defaultdict(Decimal)
            for expense in obj.expenses.all():
                totals[expense.currency] += expense.amount
        return {currency: str(amount) for currency, amount in sorted(totals.items())}


class DeliveryListSerializer(DeliveryTotalsMixin, serializers.ModelSerializer):
    point_from = PointShortSerializer(read_only=True)
    point_to = PointShortSerializer(read_only=True)
    created_by = UserShortSerializer(read_only=True)
    dispatched_by = UserShortSerializer(read_only=True)
    received_by = UserShortSerializer(read_only=True)

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    state_label = serializers.CharField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    arrived_late = serializers.BooleanField(read_only=True)
    late_minutes = serializers.IntegerField(read_only=True)
    expenses_count = serializers.IntegerField(read_only=True)
    has_expenses = serializers.BooleanField(read_only=True)
    expense_totals = serializers.SerializerMethodField()
    expense_total_converted = serializers.SerializerMethodField()
    color = serializers.SerializerMethodField()
    waypoints = DeliveryWaypointSerializer(many=True, read_only=True)
    route_points = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = Delivery
        fields = (
            "id",
            "vehicle_number",
            "point_from",
            "point_to",
            "waypoints",
            "route_points",
            "status",
            "status_display",
            "state_label",
            "dispatched_at",
            "deadline_at",
            "received_at",
            "is_overdue",
            "arrived_late",
            "late_minutes",
            "created_by",
            "dispatched_by",
            "received_by",
            "expenses_count",
            "has_expenses",
            "expense_totals",
            "expense_total_converted",
            "color",
            "created_at",
        )
        read_only_fields = fields

    @property
    def currency_rates(self) -> dict:
        """Курсы читаются один раз на весь ответ, а не на каждую строку списка."""
        from apps.expenses.rates import CurrencyRateService

        if not hasattr(self, "_currency_rates"):
            self._currency_rates = CurrencyRateService.all_rates()
        return self._currency_rates

    def get_expense_total_converted(self, obj: Delivery) -> dict:
        """Сумма расходов рейса, сведённая к сомам по текущему курсу."""
        from apps.expenses.rates import CurrencyRateService

        return CurrencyRateService.convert_totals(
            self.get_expense_totals(obj), rates=self.currency_rates
        )

    def get_color(self, obj: Delivery) -> str:
        has_expenses = getattr(obj, "has_expenses", None)
        if has_expenses is None:
            has_expenses = obj.expenses.exists()
        return obj.color(bool(has_expenses))


class DeliveryDetailSerializer(DeliveryListSerializer):
    cancelled_by = UserShortSerializer(read_only=True)
    expenses = ExpenseSerializer(many=True, read_only=True)
    events = DeliveryEventSerializer(many=True, read_only=True)
    comments = serializers.SerializerMethodField()

    class Meta(DeliveryListSerializer.Meta):
        fields = DeliveryListSerializer.Meta.fields + (
            "planned_duration_minutes",
            "dispatch_comment",
            "receive_comment",
            "cancel_comment",
            "cancelled_by",
            "cancelled_at",
            "expenses",
            "events",
            "comments",
            "updated_at",
        )
        read_only_fields = fields

    def get_comments(self, obj: Delivery) -> list:
        comments = [
            event
            for event in obj.events.all()
            if event.event_type == DeliveryEvent.EventType.COMMENT_ADDED
        ]
        return DeliveryEventSerializer(comments, many=True).data


class DeliveryCreateSerializer(serializers.Serializer):
    point_from_id = serializers.IntegerField()
    point_to_id = serializers.IntegerField()
    vehicle_number = serializers.CharField(max_length=30)
    dispatched_at = serializers.DateTimeField(required=False, allow_null=True)
    duration_hours = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False, allow_null=True, min_value=Decimal("0")
    )
    duration_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    deadline_at = serializers.DateTimeField(required=False, allow_null=True)
    waypoint_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True, max_length=10
    )
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    auto_dispatch = serializers.BooleanField(required=False, default=True)

    def validate_comment(self, value: str) -> str:
        return plain_text(value)

    def validate_vehicle_number(self, value: str) -> str:
        # plain_text: номер попадает в списки, поиск и выгрузки как есть.
        value = plain_text(value).strip().upper()
        if len(value) < 3:
            raise serializers.ValidationError("Укажите корректный номер машины.")
        if len(normalize_vehicle_number(value)) < 3:
            raise serializers.ValidationError(
                "Номер должен содержать не меньше трёх букв или цифр."
            )
        return value

    def validate(self, attrs):
        if not attrs.get("deadline_at") and not (
            attrs.get("duration_hours") or attrs.get("duration_minutes")
        ):
            raise serializers.ValidationError(
                "Укажите срок прибытия: количество часов либо конкретное время."
            )
        return attrs


class DeliveryUpdateSerializer(serializers.Serializer):
    point_from_id = serializers.IntegerField(required=False)
    point_to_id = serializers.IntegerField(required=False)
    vehicle_number = serializers.CharField(max_length=30, required=False)
    dispatched_at = serializers.DateTimeField(required=False)
    deadline_at = serializers.DateTimeField(required=False)
    duration_hours = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False, min_value=Decimal("0")
    )
    duration_minutes = serializers.IntegerField(required=False, min_value=0)
    waypoint_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True, max_length=10
    )
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")

    def validate_comment(self, value: str) -> str:
        return plain_text(value)

    def validate_vehicle_number(self, value: str) -> str:
        # plain_text: номер попадает в списки, поиск и выгрузки как есть.
        value = plain_text(value).strip().upper()
        if len(value) < 3:
            raise serializers.ValidationError("Укажите корректный номер машины.")
        if len(normalize_vehicle_number(value)) < 3:
            raise serializers.ValidationError(
                "Номер должен содержать не меньше трёх букв или цифр."
            )
        return value

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Не переданы поля для изменения.")
        return attrs


class DispatchSerializer(serializers.Serializer):
    dispatched_at = serializers.DateTimeField(required=False, allow_null=True)
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")

    def validate_comment(self, value: str) -> str:
        return plain_text(value)


class ReceiveSerializer(serializers.Serializer):
    received_at = serializers.DateTimeField(required=False, allow_null=True)
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")

    def validate_comment(self, value: str) -> str:
        return plain_text(value)


class CancelSerializer(serializers.Serializer):
    comment = serializers.CharField(max_length=500)

    def validate_comment(self, value: str) -> str:
        return plain_text(value)


class CommentSerializer(serializers.Serializer):
    comment = serializers.CharField(max_length=2000)

    def validate_comment(self, value: str) -> str:
        return plain_text(value)


class DashboardSerializer(serializers.Serializer):
    """Сводка для главной панели."""

    total = serializers.IntegerField()
    created = serializers.IntegerField()
    in_transit = serializers.IntegerField()
    overdue = serializers.IntegerField()
    arrived = serializers.IntegerField()
    arrived_late = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    with_expenses = serializers.IntegerField()
    expense_totals = serializers.DictField(child=serializers.CharField())


DELIVERY_STATUS_CHOICES = DeliveryStatus.choices
