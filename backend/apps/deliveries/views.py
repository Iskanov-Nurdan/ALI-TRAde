"""HTTP-слой рейсов."""
import logging
from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import NotFoundError, PermissionDeniedError
from apps.core.permissions import IsAdmin
from apps.core.utils import client_ip
from apps.deliveries.filters import DeliveryFilter
from apps.deliveries.models import Delivery
from apps.deliveries.repositories import DeliveryEventRepository, DeliveryRepository
from apps.deliveries.serializers import (
    CancelSerializer,
    CommentSerializer,
    DeliveryCreateSerializer,
    DeliveryDetailSerializer,
    DeliveryEventSerializer,
    DeliveryListSerializer,
    DeliveryUpdateSerializer,
    DispatchSerializer,
    PassWaypointSerializer,
    ReceiveSerializer,
)
from apps.deliveries.services import DeliveryService
from apps.expenses.rates import CurrencyRateService

logger = logging.getLogger(__name__)


class DeliveryViewSet(viewsets.ModelViewSet):
    """Рейсы: создание, отправление, приём, комментарии, история."""

    filterset_class = DeliveryFilter
    ordering_fields = ("dispatched_at", "deadline_at", "received_at", "created_at", "vehicle_number")
    ordering = ("-dispatched_at",)
    search_fields = ("vehicle_number",)

    def get_queryset(self):
        return DeliveryRepository().get_queryset()

    def get_serializer_class(self):
        if self.action in ("retrieve",):
            return DeliveryDetailSerializer
        return DeliveryListSerializer

    def get_permissions(self):
        # Изменение и удаление рейса — только администратор, остальное — любой сотрудник.
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAdmin()]
        return super().get_permissions()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.setdefault("expense_totals", None)
        return context

    def list(self, request, *args, **kwargs):
        # Ленивая фиксация просрочки в истории — без внешнего планировщика.
        DeliveryService().sync_overdue_events()

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = page if page is not None else list(queryset)
        totals = DeliveryRepository().expense_totals([row.id for row in rows])

        serializer = self.get_serializer(rows, many=True, context={**self.get_serializer_context(), "expense_totals": totals})
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        delivery = DeliveryRepository().get_detail(self.kwargs["pk"])
        if delivery is None:
            raise NotFoundError("Рейс не найден.")
        DeliveryService().sync_overdue_events()
        delivery = DeliveryRepository().get_detail(delivery.id)
        return Response(DeliveryDetailSerializer(delivery, context=self.get_serializer_context()).data)

    def create(self, request, *args, **kwargs):
        serializer = DeliveryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delivery = DeliveryService().create_delivery(
            actor=request.user, data=serializer.validated_data, ip=client_ip(request)
        )
        return Response(self._detail(delivery.id), status=http_status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance: Delivery = self.get_object()
        serializer = DeliveryUpdateSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        delivery = DeliveryService().update_delivery(
            actor=request.user, delivery=instance, data=serializer.validated_data, ip=client_ip(request)
        )
        return Response(self._detail(delivery.id))

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """Удаление рейса фиксируется в журнале аудита."""
        instance: Delivery = self.get_object()
        DeliveryService().delete_delivery(
            actor=request.user, delivery=instance, ip=client_ip(request)
        )
        return Response(status=http_status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="dispatch")
    def dispatch_vehicle(self, request, pk=None):
        """POST /api/deliveries/{id}/dispatch/ — подтверждение отправления."""
        instance: Delivery = self.get_object()
        serializer = DispatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delivery = DeliveryService().dispatch(
            actor=request.user, delivery=instance, data=serializer.validated_data, ip=client_ip(request)
        )
        return Response(self._detail(delivery.id))

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        """POST /api/deliveries/{id}/receive/ — подтверждение прибытия."""
        instance: Delivery = self.get_object()
        serializer = ReceiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delivery = DeliveryService().receive(
            actor=request.user, delivery=instance, data=serializer.validated_data, ip=client_ip(request)
        )
        return Response(self._detail(delivery.id))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """POST /api/deliveries/{id}/cancel/ — отмена рейса.

        Сотрудник отменяет только собственный рейс, администратор — любой.
        """
        instance: Delivery = self.get_object()
        if not request.user.is_admin and instance.created_by_id != request.user.id:
            raise PermissionDeniedError("Отменить можно только рейс, созданный вами.")
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delivery = DeliveryService().cancel(
            actor=request.user, delivery=instance, data=serializer.validated_data, ip=client_ip(request)
        )
        return Response(self._detail(delivery.id))

    @action(detail=True, methods=["post"], url_path=r"waypoints/(?P<waypoint_id>\d+)/pass")
    def pass_waypoint(self, request, pk=None, waypoint_id=None):
        """POST /api/deliveries/{id}/waypoints/{waypoint_id}/pass/ — отметка прохождения точки."""
        instance: Delivery = self.get_object()
        waypoint = instance.waypoints.filter(pk=waypoint_id).first()
        if waypoint is None:
            raise NotFoundError("Промежуточная точка не найдена в этом рейсе.")

        serializer = PassWaypointSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        DeliveryService().pass_waypoint(
            actor=request.user,
            delivery=instance,
            waypoint=waypoint,
            data=serializer.validated_data,
            ip=client_ip(request),
        )
        return Response(self._detail(instance.id))

    @action(detail=True, methods=["get", "post"])
    def comments(self, request, pk=None):
        """GET/POST /api/deliveries/{id}/comments/ — комментарии сотрудников."""
        instance: Delivery = self.get_object()
        if request.method == "GET":
            comments = DeliveryEventRepository().comments_for_delivery(instance.id)
            return Response(DeliveryEventSerializer(comments, many=True).data)

        serializer = CommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = DeliveryService().add_comment(
            actor=request.user, delivery=instance, comment=serializer.validated_data["comment"]
        )
        return Response(DeliveryEventSerializer(event).data, status=http_status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        """GET /api/deliveries/{id}/events/ — полная история рейса."""
        instance: Delivery = self.get_object()
        DeliveryService().sync_overdue_events()
        events = DeliveryEventRepository().for_delivery(instance.id)
        return Response(DeliveryEventSerializer(events, many=True).data)

    @action(detail=False, methods=["get"])
    def dashboard(self, request):
        """GET /api/deliveries/dashboard/ — сводка с учётом текущих фильтров."""
        DeliveryService().sync_overdue_events()
        queryset = self.filter_queryset(self.get_queryset())
        counters = DeliveryRepository().dashboard_counters(queryset)

        from apps.expenses.models import Expense

        rows = (
            Expense.objects.filter(delivery__in=queryset.values("id"))
            .values("currency")
            .annotate(total=Sum("amount"))
        )
        counters["expense_totals"] = {row["currency"]: str(row["total"]) for row in rows}
        # Разные валюты сводим к сомам по текущему курсу
        counters["expense_total_converted"] = CurrencyRateService.convert_totals(
            counters["expense_totals"]
        )
        return Response(counters)

    def _detail(self, delivery_id: int) -> dict:
        delivery = DeliveryRepository().get_detail(delivery_id)
        return DeliveryDetailSerializer(delivery, context=self.get_serializer_context()).data


class VehicleSearchView(APIView):
    """GET /api/vehicles/search/?q=1234 — поиск рейсов по номеру машины."""

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        if len(query) < 2:
            return Response(
                {"detail": "Введите не менее двух символов номера.", "code": "short_query"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        DeliveryService().sync_overdue_events()
        repository = DeliveryRepository()
        deliveries = list(repository.search_by_vehicle(query)[:100])
        totals = repository.expense_totals([d.id for d in deliveries])

        vehicles: dict[str, dict] = defaultdict(lambda: {"deliveries": 0, "totals": defaultdict(Decimal)})
        for delivery in deliveries:
            bucket = vehicles[delivery.vehicle_number]
            bucket["deliveries"] += 1
            for currency, amount in totals.get(delivery.id, {}).items():
                bucket["totals"][currency] += amount

        return Response(
            {
                "query": query,
                "count": len(deliveries),
                "vehicles": [
                    {
                        "vehicle_number": number,
                        "deliveries": data["deliveries"],
                        "expense_totals": {c: str(v) for c, v in sorted(data["totals"].items())},
                    }
                    for number, data in sorted(vehicles.items())
                ],
                "results": DeliveryListSerializer(
                    deliveries, many=True, context={"expense_totals": totals}
                ).data,
            }
        )
