"""Отчёты администратора: сводка, разрезы, выгрузка в Excel и CSV."""
import logging

from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdmin
from apps.core.utils import humanize_minutes
from apps.deliveries.filters import DeliveryFilter
from apps.deliveries.repositories import DeliveryRepository
from apps.deliveries.services import DeliveryService
from apps.expenses.filters import ExpenseFilter
from apps.expenses.repositories import ExpenseRepository
from apps.reports.exporters import export_response
from apps.reports.services import ReportService

logger = logging.getLogger(__name__)


class AdminReportMixin:
    permission_classes = (IsAdmin,)

    @staticmethod
    def _apply(filterset):
        """Отчёт по нераспознанному фильтру — это ошибка, а не выборка «всё подряд».

        DjangoFilterBackend в обычных списках вызывает is_valid() сам; отчёты
        строят фильтр напрямую, поэтому проверку нужно выполнить здесь. Иначе
        опечатка в статусе или в дате молча превращает отчёт за период в отчёт
        за всё время.
        """
        if not filterset.is_valid():
            raise ValidationError(filterset.errors)
        return filterset.qs

    def filtered_deliveries(self, request):
        DeliveryService().sync_overdue_events()
        queryset = DeliveryRepository().get_queryset()
        return self._apply(DeliveryFilter(request.query_params, queryset=queryset))

    def filtered_expenses(self, request):
        queryset = ExpenseRepository().get_queryset()
        return self._apply(ExpenseFilter(request.query_params, queryset=queryset))


class ReportSummaryView(AdminReportMixin, APIView):
    """GET /api/reports/summary/ — сводные показатели за период."""

    def get(self, request):
        deliveries = self.filtered_deliveries(request)
        service = ReportService()
        return Response(
            {
                "summary": service.summary(deliveries),
                "by_expense_type": service.by_expense_type(deliveries),
                "by_payer": service.by_payer(deliveries),
                "by_route": service.by_route(deliveries),
            }
        )


class ReportExpensesView(AdminReportMixin, APIView):
    """GET /api/reports/expenses/ — расходы в разрезах машин, рейсов и сотрудников."""

    def get(self, request):
        deliveries = self.filtered_deliveries(request)
        service = ReportService()
        return Response(
            {
                "totals": ExpenseRepository().totals_by_currency(service.expenses_for(deliveries)),
                "by_vehicle": service.by_vehicle(deliveries),
                "by_delivery": service.by_delivery(deliveries),
                "by_expense_type": service.by_expense_type(deliveries),
            }
        )


class ReportEmployeesView(AdminReportMixin, APIView):
    """GET /api/reports/employees/ — кто отправлял, принимал и добавлял расходы."""

    def get(self, request):
        deliveries = self.filtered_deliveries(request)
        return Response({"results": ReportService().by_employee(deliveries)})


class ExportDeliveriesView(AdminReportMixin, APIView):
    """GET /api/reports/export/deliveries/ — выгрузка рейсов (xlsx, ?ext=csv для CSV)."""

    def get(self, request):
        deliveries = self.filtered_deliveries(request).order_by("-dispatched_at")[:10000]
        totals = DeliveryRepository().expense_totals([d.id for d in deliveries])

        def fmt(value):
            return timezone.localtime(value).strftime("%d.%m.%Y %H:%M") if value else ""

        rows = []
        for delivery in deliveries:
            expense_str = ", ".join(
                f"{amount} {currency}" for currency, amount in sorted(totals.get(delivery.id, {}).items())
            )
            rows.append(
                [
                    delivery.id,
                    delivery.vehicle_number,
                    delivery.point_from.name,
                    " → ".join(delivery.route_points[1:-1]) or "—",
                    delivery.point_to.name,
                    delivery.created_by.full_name if delivery.created_by else "",
                    delivery.dispatched_by.full_name if delivery.dispatched_by else "",
                    fmt(delivery.dispatched_at),
                    fmt(delivery.deadline_at),
                    delivery.received_by.full_name if delivery.received_by else "",
                    fmt(delivery.received_at),
                    delivery.state_label,
                    humanize_minutes(delivery.late_minutes),
                    expense_str,
                ]
            )

        return export_response(
            request,
            "reisy",
            [
                "ID",
                "Машина",
                "Откуда",
                "Через",
                "Куда",
                "Создал",
                "Отправил",
                "Отправлена",
                "Дедлайн",
                "Принял",
                "Прибыла",
                "Статус",
                "Опоздание",
                "Расходы",
            ],
            rows,
            sheet_title="Рейсы",
        )


class ExportExpensesView(AdminReportMixin, APIView):
    """GET /api/reports/export/expenses/ — выгрузка расходов (xlsx, ?ext=csv для CSV)."""

    def get(self, request):
        expenses = self.filtered_expenses(request).order_by("-created_at")[:10000]
        rows = [
            [
                expense.id,
                expense.delivery_id,
                expense.delivery.vehicle_number,
                f"{expense.delivery.point_from.name} → {expense.delivery.point_to.name}",
                expense.expense_type.name,
                expense.amount,
                expense.currency,
                expense.get_payer_display(),
                expense.description,
                expense.comment,
                expense.created_by.full_name,
                timezone.localtime(expense.created_at).strftime("%d.%m.%Y %H:%M"),
            ]
            for expense in expenses
        ]
        return export_response(
            request,
            "rashody",
            [
                "ID",
                "Рейс",
                "Машина",
                "Маршрут",
                "Тип",
                "Сумма",
                "Валюта",
                "Плательщик",
                "Описание",
                "Комментарий",
                "Добавил",
                "Дата",
            ],
            rows,
            sheet_title="Расходы",
        )
