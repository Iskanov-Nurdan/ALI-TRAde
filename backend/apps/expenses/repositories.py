from django.db.models import Count, QuerySet, Sum

from apps.core.repositories import BaseRepository
from apps.expenses.models import Expense, ExpenseSettings, ExpenseType


class ExpenseTypeRepository(BaseRepository[ExpenseType]):
    model = ExpenseType

    def list_active(self) -> QuerySet[ExpenseType]:
        return self.get_queryset().filter(is_active=True)

    def name_exists(self, name: str, exclude_id: int | None = None) -> bool:
        qs = self.get_queryset().filter(name__iexact=name.strip())
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)
        return qs.exists()

    def code_exists(self, code: str, exclude_id: int | None = None) -> bool:
        qs = self.get_queryset().filter(code=code)
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)
        return qs.exists()

    def is_used(self, expense_type: ExpenseType) -> bool:
        return expense_type.expenses.exists()


class ExpenseRepository(BaseRepository[Expense]):
    model = Expense

    def get_queryset(self) -> QuerySet[Expense]:
        return (
            super()
            .get_queryset()
            .select_related("expense_type", "created_by", "delivery", "delivery__point_from", "delivery__point_to")
        )

    def for_delivery(self, delivery_id: int) -> QuerySet[Expense]:
        return self.get_queryset().filter(delivery_id=delivery_id)

    def totals_by_currency(self, queryset: QuerySet[Expense] | None = None) -> dict[str, str]:
        qs = queryset if queryset is not None else self.get_queryset()
        rows = qs.values("currency").annotate(total=Sum("amount")).order_by("currency")
        return {row["currency"]: str(row["total"]) for row in rows}

    def group_totals(self, queryset: QuerySet[Expense], *group_fields: str) -> list[dict]:
        return list(
            queryset.values(*group_fields)
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("-total")
        )


class ExpenseSettingsRepository:
    def load(self) -> ExpenseSettings:
        return ExpenseSettings.load()
