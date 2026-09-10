import django_filters as filters

from apps.accounts.models import User, UserRole


class UserFilter(filters.FilterSet):
    role = filters.ChoiceFilter(choices=UserRole.choices)
    is_active = filters.BooleanFilter()
    search = filters.CharFilter(method="filter_search", label="Поиск по имени или логину")

    class Meta:
        model = User
        fields = ("role", "is_active")

    def filter_search(self, queryset, name, value):
        value = (value or "").strip()
        if not value:
            return queryset
        return queryset.filter(full_name__icontains=value) | queryset.filter(login__icontains=value)
