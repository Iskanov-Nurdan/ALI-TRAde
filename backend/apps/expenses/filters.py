import django_filters as filters

from apps.deliveries.models import normalize_vehicle_number
from apps.expenses.models import Currency, Expense, Payer


class ExpenseFilter(filters.FilterSet):
    date_from = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    date_to = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")
    delivery = filters.NumberFilter(field_name="delivery_id")
    expense_type = filters.NumberFilter(field_name="expense_type_id")
    currency = filters.ChoiceFilter(choices=Currency.choices)
    payer = filters.ChoiceFilter(choices=Payer.choices)
    created_by = filters.NumberFilter(field_name="created_by_id")
    vehicle_number = filters.CharFilter(method="filter_vehicle", label="Номер машины")
    point_from = filters.NumberFilter(field_name="delivery__point_from_id")
    point_to = filters.NumberFilter(field_name="delivery__point_to_id")

    class Meta:
        model = Expense
        fields = ("delivery", "expense_type", "currency", "payer", "created_by")

    def filter_vehicle(self, queryset, name, value):
        normalized = normalize_vehicle_number(value)
        if not normalized:
            return queryset
        return queryset.filter(delivery__vehicle_number_search__contains=normalized)
