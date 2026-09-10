from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("full_name",)
    list_display = ("full_name", "login", "role", "is_active", "created_at")
    list_filter = ("role", "is_active")
    search_fields = ("full_name", "login", "phone")
    readonly_fields = ("created_at", "updated_at", "last_login")

    fieldsets = (
        (None, {"fields": ("login", "password")}),
        ("Личные данные", {"fields": ("full_name", "phone")}),
        ("Права", {"fields": ("role", "is_active", "is_staff", "is_superuser")}),
        ("Даты", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("login", "full_name", "role", "password1", "password2"),
            },
        ),
    )
