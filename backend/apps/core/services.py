"""Сервис аудита — вызывается из сервисных слоёв приложений."""
import logging
from typing import Any

from apps.core.models import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    @staticmethod
    def log(
        *,
        user=None,
        action: str,
        entity_type: str,
        entity_id: Any,
        old_value: dict | None = None,
        new_value: dict | None = None,
        ip_address: str | None = None,
    ) -> AuditLog:
        entry = AuditLog.objects.create(
            user=user,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            old_value=old_value,
            new_value=new_value,
            ip_address=ip_address,
        )
        logger.info(
            "AUDIT %s %s#%s пользователем %s",
            action,
            entity_type,
            entity_id,
            getattr(user, "login", "system"),
        )
        return entry
