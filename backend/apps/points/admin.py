from django.contrib import admin

from apps.points.models import Point


@admin.register(Point)
class PointAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "phone", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "address", "description")
    readonly_fields = ("created_at", "updated_at")
