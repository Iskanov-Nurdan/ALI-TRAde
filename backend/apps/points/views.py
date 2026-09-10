"""HTTP-слой точек."""
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.permissions import IsAdminOrReadOnly
from apps.core.utils import client_ip
from apps.points.models import Point
from apps.points.repositories import PointRepository
from apps.points.serializers import (
    PointSerializer,
    PointUpdateSerializer,
    PointWriteSerializer,
    SetActiveSerializer,
)
from apps.points.services import PointService


class PointViewSet(viewsets.ModelViewSet):
    """Справочник точек: чтение — всем, изменение — администратору."""

    serializer_class = PointSerializer
    permission_classes = (IsAdminOrReadOnly,)
    filterset_fields = ("is_active",)
    search_fields = ("name", "address", "description")
    ordering_fields = ("name", "created_at")
    ordering = ("name",)

    def get_queryset(self):
        repository = PointRepository()
        # Обычный сотрудник видит только активные точки, администратор — все.
        if self.request.user.is_authenticated and self.request.user.is_admin:
            return repository.get_queryset()
        return repository.list_active()

    def create(self, request, *args, **kwargs):
        serializer = PointWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        point = PointService().create_point(
            actor=request.user, data=serializer.validated_data, ip=client_ip(request)
        )
        return Response(PointSerializer(point).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance: Point = self.get_object()
        serializer = PointUpdateSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        point = PointService().update_point(
            actor=request.user,
            point=instance,
            data=serializer.validated_data,
            ip=client_ip(request),
        )
        return Response(PointSerializer(point).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance: Point = self.get_object()
        PointService().delete_point(actor=request.user, point=instance, ip=client_ip(request))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="set-active")
    def set_active(self, request, pk=None):
        """POST /api/points/{id}/set-active/ — включение и отключение точки."""
        instance: Point = self.get_object()
        serializer = SetActiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        point = PointService().set_active(
            actor=request.user,
            point=instance,
            is_active=serializer.validated_data["is_active"],
            ip=client_ip(request),
        )
        return Response(PointSerializer(point).data)
