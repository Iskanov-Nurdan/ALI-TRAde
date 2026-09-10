"""HTTP-слой расходов."""
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import NotFoundError
from apps.core.permissions import IsAdmin, IsAdminOrReadOnly
from apps.core.utils import client_ip
from apps.deliveries.repositories import DeliveryRepository
from apps.expenses.filters import ExpenseFilter
from apps.expenses.models import Currency, Expense, ExpenseSettings, ExpenseType, Payer
from apps.expenses.rates import BASE_CURRENCY, CurrencyRateService
from apps.expenses.repositories import ExpenseRepository, ExpenseTypeRepository
from apps.expenses.serializers import (
    CurrencyRateSerializer,
    CurrencyRateWriteSerializer,
    ExpenseCreateSerializer,
    ExpenseSerializer,
    ExpenseSettingsSerializer,
    ExpenseSettingsWriteSerializer,
    ExpenseTypeSerializer,
    ExpenseTypeWriteSerializer,
    ExpenseUpdateSerializer,
)
from apps.expenses.services import ExpenseService, ExpenseSettingsService, ExpenseTypeService


class ExpenseTypeViewSet(viewsets.ModelViewSet):
    """Справочник типов расходов: чтение — всем, изменение — администратору."""

    serializer_class = ExpenseTypeSerializer
    permission_classes = (IsAdminOrReadOnly,)
    filterset_fields = ("is_active",)
    ordering_fields = ("sort_order", "name")
    ordering = ("sort_order", "name")
    pagination_class = None

    def get_queryset(self):
        repository = ExpenseTypeRepository()
        if self.request.user.is_authenticated and self.request.user.is_admin:
            return repository.get_queryset()
        return repository.list_active()

    def create(self, request, *args, **kwargs):
        serializer = ExpenseTypeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expense_type = ExpenseTypeService().create_type(
            actor=request.user, data=serializer.validated_data, ip=client_ip(request)
        )
        return Response(ExpenseTypeSerializer(expense_type).data, status=http_status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        kwargs.pop("partial", False)
        instance: ExpenseType = self.get_object()
        serializer = ExpenseTypeWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        expense_type = ExpenseTypeService().update_type(
            actor=request.user,
            expense_type=instance,
            data=serializer.validated_data,
            ip=client_ip(request),
        )
        return Response(ExpenseTypeSerializer(expense_type).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance: ExpenseType = self.get_object()
        ExpenseTypeService().delete_type(
            actor=request.user, expense_type=instance, ip=client_ip(request)
        )
        return Response(status=http_status.HTTP_204_NO_CONTENT)


class ExpenseViewSet(viewsets.ModelViewSet):
    """Расходы по рейсам. Добавлять может любой сотрудник и на любом этапе рейса."""

    serializer_class = ExpenseSerializer
    filterset_class = ExpenseFilter
    ordering_fields = ("created_at", "amount")
    ordering = ("-created_at",)
    search_fields = ("description", "comment", "delivery__vehicle_number")

    def get_queryset(self):
        return ExpenseRepository().get_queryset()

    def get_permissions(self):
        # Редактировать и удалять расходы может только администратор.
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAdmin()]
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
        serializer = ExpenseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        delivery_id = request.data.get("delivery") or request.data.get("delivery_id")
        delivery = DeliveryRepository().get_by_id(delivery_id) if delivery_id else None
        if delivery is None:
            raise NotFoundError("Рейс не найден — расход привязывается к конкретному рейсу.")

        expense = ExpenseService().add_expense(
            actor=request.user,
            delivery=delivery,
            data=serializer.validated_data,
            ip=client_ip(request),
        )
        return Response(ExpenseSerializer(expense).data, status=http_status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance: Expense = self.get_object()
        serializer = ExpenseUpdateSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        expense = ExpenseService().update_expense(
            actor=request.user, expense=instance, data=serializer.validated_data, ip=client_ip(request)
        )
        return Response(ExpenseSerializer(expense).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance: Expense = self.get_object()
        ExpenseService().delete_expense(actor=request.user, expense=instance, ip=client_ip(request))
        return Response(status=http_status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"])
    def totals(self, request):
        """GET /api/expenses/totals/ — итоги по валютам с учётом фильтров."""
        queryset = self.filter_queryset(self.get_queryset())
        totals = ExpenseRepository().totals_by_currency(queryset)
        return Response(
            {
                "count": queryset.count(),
                "totals": totals,
                "converted": CurrencyRateService.convert_totals(totals),
            }
        )


class DeliveryExpenseView(APIView):
    """GET/POST /api/deliveries/{id}/expenses/ — расходы конкретного рейса."""

    def get(self, request, delivery_id: int):
        delivery = DeliveryRepository().get_by_id(delivery_id)
        if delivery is None:
            raise NotFoundError("Рейс не найден.")
        repository = ExpenseRepository()
        expenses = repository.for_delivery(delivery_id)
        totals = repository.totals_by_currency(expenses)
        return Response(
            {
                "results": ExpenseSerializer(expenses, many=True).data,
                "totals": totals,
                "converted": CurrencyRateService.convert_totals(totals),
            }
        )

    def post(self, request, delivery_id: int):
        delivery = DeliveryRepository().get_by_id(delivery_id)
        if delivery is None:
            raise NotFoundError("Рейс не найден.")
        serializer = ExpenseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expense = ExpenseService().add_expense(
            actor=request.user,
            delivery=delivery,
            data=serializer.validated_data,
            ip=client_ip(request),
        )
        return Response(ExpenseSerializer(expense).data, status=http_status.HTTP_201_CREATED)


class ExpenseSettingsView(APIView):
    """Настройка правила «расход выше порога оплачивает …»."""

    def get_permissions(self):
        if self.request.method == "GET":
            return super().get_permissions()
        return [IsAdmin()]

    def get(self, request):
        return Response(ExpenseSettingsSerializer(ExpenseSettings.load()).data)

    def put(self, request):
        serializer = ExpenseSettingsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings = ExpenseSettingsService().update(
            actor=request.user, data=serializer.validated_data, ip=client_ip(request)
        )
        return Response(ExpenseSettingsSerializer(settings).data)


class ExpenseDictionaryView(APIView):
    """GET /api/expenses/dictionaries/ — валюты и плательщики для форм."""

    def get(self, request):
        return Response(
            {
                "currencies": [{"value": c.value, "label": c.label} for c in Currency],
                "payers": [{"value": p.value, "label": p.label} for p in Payer],
            }
        )


class CurrencyRateView(APIView):
    """Курсы валют к сому: смотрят все, меняет администратор."""

    def get_permissions(self):
        if self.request.method == "GET":
            return super().get_permissions()
        return [IsAdmin()]

    def get(self, request):
        rates = CurrencyRateService.list_rates()
        return Response(
            {"base": BASE_CURRENCY, "results": CurrencyRateSerializer(rates, many=True).data}
        )

    def put(self, request):
        serializer = CurrencyRateWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rates = CurrencyRateService.update_rates(
            actor=request.user, rates=serializer.validated_data["rates"], ip=client_ip(request)
        )
        return Response(
            {"base": BASE_CURRENCY, "results": CurrencyRateSerializer(rates, many=True).data}
        )
