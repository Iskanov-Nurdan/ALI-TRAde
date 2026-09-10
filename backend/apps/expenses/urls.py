from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.expenses.views import (
    CurrencyRateView,
    DeliveryExpenseView,
    ExpenseDictionaryView,
    ExpenseSettingsView,
    ExpenseTypeViewSet,
    ExpenseViewSet,
)

router = DefaultRouter()
router.register("expenses", ExpenseViewSet, basename="expense")
router.register("expense-types", ExpenseTypeViewSet, basename="expense-type")

urlpatterns = [
    path("expenses/dictionaries/", ExpenseDictionaryView.as_view(), name="expense-dictionaries"),
    path("expenses/settings/", ExpenseSettingsView.as_view(), name="expense-settings"),
    path("expenses/rates/", CurrencyRateView.as_view(), name="currency-rates"),
    path(
        "deliveries/<int:delivery_id>/expenses/",
        DeliveryExpenseView.as_view(),
        name="delivery-expenses",
    ),
    path("", include(router.urls)),
]
