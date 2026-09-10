"""Служебные эндпоинты: health-check и журнал аудита."""
from django.db import connection
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AuditLog
from apps.core.permissions import IsAdmin
from apps.core.serializers import AuditLogSerializer


class HealthView(APIView):
    """GET /health/ — проверка доступности сервиса и базы данных."""

    permission_classes = (AllowAny,)
    authentication_classes = ()

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            database = "ok"
        except Exception:  # noqa: BLE001 — наружу отдаём только статус
            database = "error"
        status_code = 200 if database == "ok" else 503
        return Response({"status": "ok" if database == "ok" else "degraded", "database": database}, status=status_code)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/audit/ — журнал действий, только для администратора."""

    serializer_class = AuditLogSerializer
    permission_classes = (IsAdmin,)
    filterset_fields = ("action", "entity_type", "user")
    search_fields = ("entity_type", "entity_id")
    ordering_fields = ("created_at",)
    ordering = ("-created_at",)

    def get_queryset(self):
        return AuditLog.objects.select_related("user").all()
