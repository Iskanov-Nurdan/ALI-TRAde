from django.contrib import admin

from apps.deliveries.models import Delivery, DeliveryEvent, DeliveryWaypoint


class DeliveryEventInline(admin.TabularInline):
    model = DeliveryEvent
    extra = 0
    readonly_fields = ("event_type", "user", "event_time", "comment", "metadata")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class DeliveryWaypointInline(admin.TabularInline):
    model = DeliveryWaypoint
    extra = 0
    autocomplete_fields = ("point",)
    readonly_fields = ("passed_at", "passed_by")


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "vehicle_number",
        "point_from",
        "point_to",
        "status",
        "dispatched_at",
        "deadline_at",
        "received_at",
    )
    list_filter = ("status", "point_from", "point_to")
    search_fields = ("vehicle_number", "vehicle_number_search")
    date_hierarchy = "dispatched_at"
    autocomplete_fields = ("point_from", "point_to")
    readonly_fields = ("vehicle_number_search", "created_at", "updated_at", "deadline_passed_logged")
    inlines = (DeliveryWaypointInline, DeliveryEventInline)


@admin.register(DeliveryEvent)
class DeliveryEventAdmin(admin.ModelAdmin):
    list_display = ("delivery", "event_type", "user", "event_time")
    list_filter = ("event_type",)
    search_fields = ("delivery__vehicle_number", "comment")
    readonly_fields = ("delivery", "event_type", "user", "event_time", "comment", "metadata")
