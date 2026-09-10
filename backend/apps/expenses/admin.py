from django.contrib import admin

from apps.expenses.models import CurrencyRate, Expense, ExpenseSettings, ExpenseType


@admin.register(ExpenseType)
class ExpenseTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("id", "delivery", "expense_type", "amount", "currency", "payer", "created_by", "created_at")
    list_filter = ("currency", "payer", "expense_type")
    search_fields = ("description", "comment", "delivery__vehicle_number")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")


@admin.register(ExpenseSettings)
class ExpenseSettingsAdmin(admin.ModelAdmin):
    list_display = ("auto_payer_enabled", "threshold_amount", "threshold_currency", "payer_above", "payer_below")

    def has_add_permission(self, request):
        return not ExpenseSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CurrencyRate)
class CurrencyRateAdmin(admin.ModelAdmin):
    list_display = ("code", "rate", "updated_by", "updated_at")
    readonly_fields = ("updated_at",)
