import django_filters as filters
from django.db.models import F
from django.utils import timezone

from apps.deliveries.models import Delivery, DeliveryStatus, normalize_vehicle_number


class DeliveryFilter(filters.FilterSet):
    """Фильтры рейсов. Все параметры комбинируются между собой."""

    date_from = filters.DateTimeFilter(field_name="dispatched_at", lookup_expr="gte")
    date_to = filters.DateTimeFilter(field_name="dispatched_at", lookup_expr="lte")
    vehicle_number = filters.CharFilter(method="filter_vehicle", label="Номер машины")
    point_from = filters.NumberFilter(field_name="point_from_id")
    point_to = filters.NumberFilter(field_name="point_to_id")
    dispatched_by = filters.NumberFilter(field_name="dispatched_by_id")
    received_by = filters.NumberFilter(field_name="received_by_id")
    created_by = filters.NumberFilter(field_name="created_by_id")
    status = filters.MultipleChoiceFilter(choices=DeliveryStatus.choices)
    has_expenses = filters.BooleanFilter(method="filter_has_expenses", label="Есть расход")
    state = filters.ChoiceFilter(
        method="filter_state",
        label="Состояние",
        choices=(
            ("in_transit", "В пути без просрочки"),
            ("overdue", "Просроченные"),
            ("arrived", "Прибывшие"),
            ("arrived_late", "Прибывшие с опозданием"),
            ("arrived_on_time", "Прибывшие вовремя"),
            ("active", "Активные (создан или в пути)"),
        ),
    )

    class Meta:
        model = Delivery
        fields = ("status", "point_from", "point_to", "dispatched_by", "received_by")

    def filter_vehicle(self, queryset, name, value):
        if not (value or "").strip():
            return queryset
        normalized = normalize_vehicle_number(value)
        if not normalized:
            # В запросе только знаки препинания — совпадений быть не может
            return queryset.none()
        return queryset.filter(vehicle_number_search__contains=normalized)

    def filter_has_expenses(self, queryset, name, value):
        if value is None:
            return queryset
        return queryset.filter(expenses__isnull=not value).distinct()

    def filter_state(self, queryset, name, value):
        now = timezone.now()
        if value == "overdue":
            return queryset.filter(status=DeliveryStatus.IN_TRANSIT, deadline_at__lt=now)
        if value == "in_transit":
            return queryset.filter(status=DeliveryStatus.IN_TRANSIT, deadline_at__gte=now)
        if value == "arrived":
            return queryset.filter(status=DeliveryStatus.ARRIVED)
        if value == "arrived_late":
            return queryset.filter(status=DeliveryStatus.ARRIVED, received_at__gt=F("deadline_at"))
        if value == "arrived_on_time":
            return queryset.filter(status=DeliveryStatus.ARRIVED, received_at__lte=F("deadline_at"))
        if value == "active":
            return queryset.filter(status__in=[DeliveryStatus.CREATED, DeliveryStatus.IN_TRANSIT])
        return queryset
