"""Бизнес-логика управления точками."""
import logging

from django.db import transaction

from apps.core.exceptions import BusinessError
from apps.core.models import AuditLog
from apps.core.services import AuditService
from apps.points.models import Point
from apps.points.repositories import PointRepository

logger = logging.getLogger(__name__)


class PointService:
    def __init__(self, repository: PointRepository | None = None) -> None:
        self.repository = repository or PointRepository()

    @staticmethod
    def _snapshot(point: Point) -> dict:
        return {
            "name": point.name,
            "address": point.address,
            "phone": point.phone,
            "description": point.description,
            "is_active": point.is_active,
        }

    @transaction.atomic
    def create_point(self, *, actor, data: dict, ip: str | None = None) -> Point:
        name = data["name"].strip()
        if self.repository.name_exists(name):
            raise BusinessError("Точка с таким названием уже существует.")

        point = self.repository.create(
            name=name,
            address=data.get("address", "").strip(),
            phone=data.get("phone", "").strip(),
            description=data.get("description", "").strip(),
            is_active=data.get("is_active", True),
        )
        AuditService.log(
            user=actor,
            action=AuditLog.Action.CREATE,
            entity_type="point",
            entity_id=point.id,
            new_value=self._snapshot(point),
            ip_address=ip,
        )
        logger.info("Создана точка %s", point.name)
        return point

    @transaction.atomic
    def update_point(self, *, actor, point: Point, data: dict, ip: str | None = None) -> Point:
        old = self._snapshot(point)

        if "name" in data:
            name = data["name"].strip()
            if self.repository.name_exists(name, exclude_id=point.id):
                raise BusinessError("Точка с таким названием уже существует.")
            point.name = name
        for field in ("address", "phone", "description"):
            if field in data:
                setattr(point, field, (data[field] or "").strip())
        if "is_active" in data:
            point.is_active = data["is_active"]

        point.save()

        AuditService.log(
            user=actor,
            action=AuditLog.Action.UPDATE,
            entity_type="point",
            entity_id=point.id,
            old_value=old,
            new_value=self._snapshot(point),
            ip_address=ip,
        )
        return point

    @transaction.atomic
    def set_active(self, *, actor, point: Point, is_active: bool, ip: str | None = None) -> Point:
        if point.is_active == is_active:
            return point

        point.is_active = is_active
        point.save(update_fields=["is_active", "updated_at"])

        AuditService.log(
            user=actor,
            action=AuditLog.Action.UNBLOCK if is_active else AuditLog.Action.BLOCK,
            entity_type="point",
            entity_id=point.id,
            old_value={"is_active": not is_active},
            new_value={"is_active": is_active},
            ip_address=ip,
        )
        logger.info("Точка %s %s", point.name, "включена" if is_active else "отключена")
        return point

    @transaction.atomic
    def delete_point(self, *, actor, point: Point, ip: str | None = None) -> None:
        if self.repository.has_deliveries(point):
            raise BusinessError(
                "Точка используется в рейсах. Её можно только отключить, но не удалить."
            )
        snapshot = self._snapshot(point)
        point_id = point.id
        self.repository.delete(point)

        AuditService.log(
            user=actor,
            action=AuditLog.Action.DELETE,
            entity_type="point",
            entity_id=point_id,
            old_value=snapshot,
            ip_address=ip,
        )
        logger.warning("Точка #%s удалена", point_id)
