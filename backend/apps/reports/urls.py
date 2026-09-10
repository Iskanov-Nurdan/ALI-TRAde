from django.urls import path

from apps.reports.views import (
    ExportDeliveriesView,
    ExportExpensesView,
    ReportEmployeesView,
    ReportExpensesView,
    ReportSummaryView,
)

urlpatterns = [
    path("reports/summary/", ReportSummaryView.as_view(), name="report-summary"),
    path("reports/expenses/", ReportExpensesView.as_view(), name="report-expenses"),
    path("reports/employees/", ReportEmployeesView.as_view(), name="report-employees"),
    path("reports/export/deliveries/", ExportDeliveriesView.as_view(), name="export-deliveries"),
    path("reports/export/expenses/", ExportExpensesView.as_view(), name="export-expenses"),
]
