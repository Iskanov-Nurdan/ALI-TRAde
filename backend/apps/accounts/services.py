"""Бизнес-логика работы с сотрудниками."""
import logging

from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.accounts.repositories import UserRepository
from apps.core.exceptions import BusinessError
from apps.core.models import AuditLog
from apps.core.services import AuditService

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, repository: UserRepository | None = None) -> None:
        self.repository = repository or UserRepository()

    @staticmethod
    def _snapshot(user: User) -> dict:
        return {
            "full_name": user.full_name,
            "login": user.login,
            "phone": user.phone,
            "role": user.role,
            "is_active": user.is_active,
        }

    @transaction.atomic
    def create_user(self, *, actor: User, data: dict, ip: str | None = None) -> User:
        login = data["login"].strip().lower()
        if self.repository.login_exists(login):
            raise BusinessError("Пользователь с таким логином уже существует.")

        password = data["password"]
        validate_password(password)

        user = User(
            full_name=data["full_name"].strip(),
            login=login,
            phone=data.get("phone", "").strip(),
            role=data.get("role", UserRole.EMPLOYEE),
            is_active=data.get("is_active", True),
        )
        user.is_staff = user.role == UserRole.ADMIN
        user.set_password(password)
        user.save()

        AuditService.log(
            user=actor,
            action=AuditLog.Action.CREATE,
            entity_type="user",
            entity_id=user.id,
            new_value=self._snapshot(user),
            ip_address=ip,
        )
        logger.info("Создан сотрудник %s администратором %s", user.login, actor.login)
        return user

    @transaction.atomic
    def update_user(self, *, actor: User, user: User, data: dict, ip: str | None = None) -> User:
        old = self._snapshot(user)

        if "login" in data:
            login = data["login"].strip().lower()
            if self.repository.login_exists(login, exclude_id=user.id):
                raise BusinessError("Пользователь с таким логином уже существует.")
            user.login = login

        if "full_name" in data:
            user.full_name = data["full_name"].strip()
        if "phone" in data:
            user.phone = data["phone"].strip()
        if "role" in data:
            if user.id == actor.id and data["role"] != UserRole.ADMIN:
                raise BusinessError("Нельзя снять с себя права администратора.")
            user.role = data["role"]
            user.is_staff = user.role == UserRole.ADMIN
        if "is_active" in data:
            if user.id == actor.id and not data["is_active"]:
                raise BusinessError("Нельзя заблокировать собственную учётную запись.")
            user.is_active = data["is_active"]

        password = data.get("password")
        if password:
            validate_password(password, user)
            user.set_password(password)

        user.save()

        AuditService.log(
            user=actor,
            action=AuditLog.Action.UPDATE,
            entity_type="user",
            entity_id=user.id,
            old_value=old,
            new_value=self._snapshot(user),
            ip_address=ip,
        )
        return user

    @transaction.atomic
    def set_active(self, *, actor: User, user: User, is_active: bool, ip: str | None = None) -> User:
        if user.id == actor.id and not is_active:
            raise BusinessError("Нельзя заблокировать собственную учётную запись.")
        if user.is_admin and not is_active and self.repository.count_active_admins(exclude_id=user.id) == 0:
            raise BusinessError("В системе должен остаться хотя бы один активный администратор.")
        if user.is_active == is_active:
            return user

        user.is_active = is_active
        user.save(update_fields=["is_active", "updated_at"])

        AuditService.log(
            user=actor,
            action=AuditLog.Action.UNBLOCK if is_active else AuditLog.Action.BLOCK,
            entity_type="user",
            entity_id=user.id,
            old_value={"is_active": not is_active},
            new_value={"is_active": is_active},
            ip_address=ip,
        )
        logger.info("Сотрудник %s %s", user.login, "разблокирован" if is_active else "заблокирован")
        return user

    @transaction.atomic
    def delete_user(self, *, actor: User, user: User, ip: str | None = None) -> None:
        if user.id == actor.id:
            raise BusinessError("Нельзя удалить собственную учётную запись.")
        if user.is_admin and self.repository.count_active_admins(exclude_id=user.id) == 0:
            raise BusinessError("В системе должен остаться хотя бы один активный администратор.")

        # Сотрудник, чьи действия уже записаны в рейсах, удалению не подлежит:
        # иначе потерялась бы история «кто отправил» и «кто принял».
        # Комментарии и прочие записи истории рейса — такая же история.
        linked = (
            user.created_deliveries.exists()
            or user.dispatched_deliveries.exists()
            or user.received_deliveries.exists()
            or user.cancelled_deliveries.exists()
            or user.created_expenses.exists()
            or user.passed_waypoints.exists()
            or user.delivery_events.exists()
        )
        if linked:
            raise BusinessError(
                "Сотрудник уже участвовал в рейсах или расходах. "
                "Его можно заблокировать, но не удалить — иначе потеряется история."
            )

        snapshot = self._snapshot(user)
        user_id = user.id
        # Мягкое удаление: записи журнала аудита ссылаются на сотрудника через
        # SET_NULL, поэтому физическое удаление оставило бы их без автора.
        # Учётная запись перестаёт существовать для системы: она заблокирована,
        # скрыта из всех выборок, а логин освобождается под нового сотрудника.
        user.is_active = False
        user.deleted_at = timezone.now()
        user.login = f"deleted.{user_id}.{user.login}"[:60]
        user.set_unusable_password()
        user.save(update_fields=["is_active", "deleted_at", "login", "password", "updated_at"])

        AuditService.log(
            user=actor,
            action=AuditLog.Action.DELETE,
            entity_type="user",
            entity_id=user_id,
            old_value=snapshot,
            ip_address=ip,
        )
        logger.warning("Сотрудник #%s удалён администратором %s", user_id, actor.login)

    @transaction.atomic
    def change_own_password(
        self, *, user: User, current_password: str, new_password: str, ip: str | None = None
    ) -> None:
        if not user.check_password(current_password):
            raise BusinessError("Текущий пароль указан неверно.")
        validate_password(new_password, user)
        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])

        # Смена пароля — значимое действие: она обесценивает все выданные токены
        # и должна быть видна в журнале наравне с остальными операциями.
        AuditService.log(
            user=user,
            action=AuditLog.Action.UPDATE,
            entity_type="user",
            entity_id=user.id,
            new_value={"password_changed": True},
            ip_address=ip,
        )
        logger.info("Пользователь %s сменил пароль", user.login)
