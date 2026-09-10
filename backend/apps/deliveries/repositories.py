"""Доступ к данным рейсов и истории событий."""
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Count, Exists, F, OuterRef, Q, QuerySet, Sum
from django.utils import timezone

from apps.core.repositories import BaseRepository
from apps.deliveries.models import Delivery, DeliveryEvent, DeliveryStatus, normalize_vehicle_number


class DeliveryRepository(BaseRepository[Delivery]):
    model = Delivery

    def get_queryset(self) -> QuerySet[Delivery]:
        from apps.expenses.models import Expense

        expenses = Expense.objects.filter(delivery=OuterRef("pk"))
        return (
            super()
            .get_queryset()
            .select_related(
                "point_from", "point_to", "created_by", "dispatched_by", "received_by", "cancelled_by"
            )
            .prefetch_related("waypoints__point", "waypoints__passed_by")
            .annotate(
                expenses_count=Count("expenses", distinct=True),
                has_expenses=Exists(expenses),
            )
        )

    def get_detail(self, delivery_id) -> Delivery | None:
        """Некорректный идентификатор — «не найдено», а не ошибка сервера."""
        try:
            return (
                self.get_queryset()
                .prefetch_related("expenses__expense_type", "expenses__created_by", "events__user")
                .filter(pk=delivery_id)
                .first()
            )
        except (ValueError, TypeError, ValidationError):
            return None

    def search_by_vehicle(self, query: str) -> QuerySet[Delivery]:
        normalized = normalize_vehicle_number(query)
        if not normalized:
            return self.get_queryset().none()
        return self.get_queryset().filter(vehicle_number_search__contains=normalized)

    def overdue_queryset(self) -> QuerySet[Delivery]:
        return self.get_queryset().filter(
            status=DeliveryStatus.IN_TRANSIT, deadline_at__lt=timezone.now()
        )

    def unlogged_overdue(self) -> QuerySet[Delivery]:
        """Просроченные рейсы, для которых событие DEADLINE_PASSED ещё не записано."""
        return Delivery.objects.filter(
            status=DeliveryStatus.IN_TRANSIT,
            deadline_at__lt=timezone.now(),
            deadline_passed_logged=False,
        )

    def expense_totals(self, delivery_ids: list[int]) -> dict[int, dict[str, Decimal]]:
        """Суммы расходов по каждому рейсу в разрезе валют."""
        from apps.expenses.models import Expense

        if not delivery_ids:
            return {}
        rows = (
            Expense.objects.filter(delivery_id__in=delivery_ids)
            .values("delivery_id", "currency")
            .annotate(total=Sum("amount"))
        )
        totals: dict[int, dict[str, Decimal]] = defaultdict(dict)
        for row in rows:
            totals[row["delivery_id"]][row["currency"]] = row["total"]
        return dict(totals)

    def dashboard_counters(self, queryset: QuerySet[Delivery] | None = None) -> dict:
        """Сводные показатели для главной панели."""
        qs = queryset if queryset is not None else self.get_queryset()
        now = timezone.now()

        in_transit = qs.filter(status=DeliveryStatus.IN_TRANSIT)
        arrived = qs.filter(status=DeliveryStatus.ARRIVED)
        return {
            "total": qs.count(),
            "created": qs.filter(status=DeliveryStatus.CREATED).count(),
            "in_transit": in_transit.filter(deadline_at__gte=now).count(),
            "overdue": in_transit.filter(deadline_at__lt=now).count(),
            "arrived": arrived.count(),
            "arrived_late": arrived.filter(received_at__gt=F("deadline_at")).count(),
            "cancelled": qs.filter(status=DeliveryStatus.CANCELLED).count(),
            "with_expenses": qs.filter(expenses__isnull=False).distinct().count(),
        }


class DeliveryEventRepository(BaseRepository[DeliveryEvent]):
    model = DeliveryEvent

    def get_queryset(self) -> QuerySet[DeliveryEvent]:
        return super().get_queryset().select_related("user", "delivery")

    def for_delivery(self, delivery_id: int) -> QuerySet[DeliveryEvent]:
        return self.get_queryset().filter(delivery_id=delivery_id)

    def comments_for_delivery(self, delivery_id: int) -> QuerySet[DeliveryEvent]:
        return self.for_delivery(delivery_id).filter(
            event_type=DeliveryEvent.EventType.COMMENT_ADDED
        )

    def exists_for_delivery(self, delivery_id: int, event_type: str) -> bool:
        return self.get_queryset().filter(delivery_id=delivery_id, event_type=event_type).exists()

    def bulk_create(self, events: list[DeliveryEvent]) -> list[DeliveryEvent]:
        return DeliveryEvent.objects.bulk_create(events)

    def recent(self, limit: int = 50) -> QuerySet[DeliveryEvent]:
        return self.get_queryset().order_by("-event_time", "-id")[:limit]

    def search(self, *, delivery_ids: list[int] | None = None, q: Q | None = None):
        qs = self.get_queryset()
        if delivery_ids is not None:
            qs = qs.filter(delivery_id__in=delivery_ids)
        if q is not None:
            qs = qs.filter(q)
        return qs
