"""Аналитика по рейсам и расходам за период."""
import logging

from django.db.models import Count, F, Q, QuerySet, Sum

from apps.deliveries.models import Delivery, DeliveryStatus
from apps.deliveries.repositories import DeliveryRepository
from apps.expenses.models import Expense
from apps.expenses.rates import CurrencyRateService
from apps.expenses.repositories import ExpenseRepository

logger = logging.getLogger(__name__)


class ReportService:
    def __init__(
        self,
        delivery_repository: DeliveryRepository | None = None,
        expense_repository: ExpenseRepository | None = None,
    ) -> None:
        self.deliveries = delivery_repository or DeliveryRepository()
        self.expenses = expense_repository or ExpenseRepository()

    def expenses_for(self, deliveries: QuerySet[Delivery]) -> QuerySet[Expense]:
        return self.expenses.get_queryset().filter(delivery__in=deliveries.values("id"))

    def summary(self, deliveries: QuerySet[Delivery]) -> dict:
        counters = self.deliveries.dashboard_counters(deliveries)
        expenses = self.expenses_for(deliveries)
        counters["expense_totals"] = self.expenses.totals_by_currency(expenses)
        counters["expense_total_converted"] = CurrencyRateService.convert_totals(
            counters["expense_totals"]
        )
        counters["expenses_count"] = expenses.count()
        return counters

    def by_expense_type(self, deliveries: QuerySet[Delivery]) -> list[dict]:
        rows = (
            self.expenses_for(deliveries)
            .values("expense_type__name", "currency")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("expense_type__name", "currency")
        )
        return [
            {
                "expense_type": row["expense_type__name"],
                "currency": row["currency"],
                "total": str(row["total"]),
                "count": row["count"],
            }
            for row in rows
        ]

    def by_vehicle(self, deliveries: QuerySet[Delivery], limit: int = 100) -> list[dict]:
        rows = (
            self.expenses_for(deliveries)
            .values("delivery__vehicle_number", "currency")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("-total")[:limit]
        )
        return [
            {
                "vehicle_number": row["delivery__vehicle_number"],
                "currency": row["currency"],
                "total": str(row["total"]),
                "count": row["count"],
            }
            for row in rows
        ]

    def by_delivery(self, deliveries: QuerySet[Delivery], limit: int = 100) -> list[dict]:
        rows = (
            self.expenses_for(deliveries)
            .values(
                "delivery_id",
                "delivery__vehicle_number",
                "delivery__point_from__name",
                "delivery__point_to__name",
                "currency",
            )
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("-total")[:limit]
        )
        return [
            {
                "delivery_id": row["delivery_id"],
                "vehicle_number": row["delivery__vehicle_number"],
                "route": f"{row['delivery__point_from__name']} → {row['delivery__point_to__name']}",
                "currency": row["currency"],
                "total": str(row["total"]),
                "count": row["count"],
            }
            for row in rows
        ]

    def by_payer(self, deliveries: QuerySet[Delivery]) -> list[dict]:
        rows = (
            self.expenses_for(deliveries)
            .values("payer", "currency")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("payer", "currency")
        )
        payer_labels = dict(Expense._meta.get_field("payer").choices)
        return [
            {
                "payer": row["payer"],
                "payer_display": payer_labels.get(row["payer"], row["payer"]),
                "currency": row["currency"],
                "total": str(row["total"]),
                "count": row["count"],
            }
            for row in rows
        ]

    def by_employee(self, deliveries: QuerySet[Delivery]) -> list[dict]:
        """Активность сотрудников: отправления, приёмы и добавленные расходы."""
        dispatched = (
            deliveries.exclude(dispatched_by__isnull=True)
            .values("dispatched_by_id", "dispatched_by__full_name")
            .annotate(count=Count("id"))
        )
        received = (
            deliveries.exclude(received_by__isnull=True)
            .values("received_by_id", "received_by__full_name")
            .annotate(count=Count("id"))
        )
        expenses = (
            self.expenses_for(deliveries)
            .values("created_by_id", "created_by__full_name", "currency")
            .annotate(total=Sum("amount"), count=Count("id"))
        )

        stats: dict[int, dict] = {}

        def bucket(user_id: int, name: str) -> dict:
            return stats.setdefault(
                user_id,
                {
                    "user_id": user_id,
                    "full_name": name,
                    "dispatched": 0,
                    "received": 0,
                    "expenses_count": 0,
                    "expense_totals": {},
                },
            )

        for row in dispatched:
            bucket(row["dispatched_by_id"], row["dispatched_by__full_name"])["dispatched"] = row["count"]
        for row in received:
            bucket(row["received_by_id"], row["received_by__full_name"])["received"] = row["count"]
        for row in expenses:
            item = bucket(row["created_by_id"], row["created_by__full_name"])
            item["expenses_count"] += row["count"]
            item["expense_totals"][row["currency"]] = str(row["total"])

        return sorted(stats.values(), key=lambda item: item["full_name"])

    def by_route(self, deliveries: QuerySet[Delivery]) -> list[dict]:
        rows = (
            deliveries.values("point_from__name", "point_to__name")
            .annotate(
                count=Count("id"),
                arrived=Count("id", filter=Q(status=DeliveryStatus.ARRIVED)),
                late=Count("id", filter=Q(status=DeliveryStatus.ARRIVED, received_at__gt=F("deadline_at"))),
            )
            .order_by("-count")
        )
        return [
            {
                "route": f"{row['point_from__name']} → {row['point_to__name']}",
                "count": row["count"],
                "arrived": row["arrived"],
                "arrived_late": row["late"],
            }
            for row in rows
        ]
