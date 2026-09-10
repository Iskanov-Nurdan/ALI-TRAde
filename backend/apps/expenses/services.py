"""Бизнес-логика расходов: добавление к рейсу в любой момент, правило плательщика."""
import logging
import re

from django.db import transaction
from django.utils.text import slugify

from apps.core.exceptions import BusinessError
from apps.core.models import AuditLog
from apps.core.services import AuditService
from apps.deliveries.models import Delivery, DeliveryEvent
from apps.deliveries.services import DeliveryEventService
from apps.expenses.models import Expense, ExpenseSettings, ExpenseType, Payer
from apps.expenses.repositories import ExpenseRepository, ExpenseTypeRepository

logger = logging.getLogger(__name__)


def make_code(name: str) -> str:
    code = slugify(name, allow_unicode=False)
    if not code:
        code = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (code or "type")[:40]


class ExpenseTypeService:
    def __init__(self, repository: ExpenseTypeRepository | None = None) -> None:
        self.repository = repository or ExpenseTypeRepository()

    @transaction.atomic
    def create_type(self, *, actor, data: dict, ip: str | None = None) -> ExpenseType:
        name = data["name"].strip()
        if self.repository.name_exists(name):
            raise BusinessError("Такой тип расхода уже существует.")

        code = (data.get("code") or make_code(name)).lower()
        suffix = 1
        base_code = code
        while self.repository.code_exists(code):
            suffix += 1
            code = f"{base_code[:36]}-{suffix}"

        expense_type = self.repository.create(
            name=name,
            code=code,
            sort_order=data.get("sort_order", 100),
            is_active=data.get("is_active", True),
        )
        AuditService.log(
            user=actor,
            action=AuditLog.Action.CREATE,
            entity_type="expense_type",
            entity_id=expense_type.id,
            new_value={"name": name, "code": code},
            ip_address=ip,
        )
        return expense_type

    @transaction.atomic
    def update_type(self, *, actor, expense_type: ExpenseType, data: dict, ip: str | None = None) -> ExpenseType:
        old = {"name": expense_type.name, "is_active": expense_type.is_active}

        if "name" in data:
            name = data["name"].strip()
            if self.repository.name_exists(name, exclude_id=expense_type.id):
                raise BusinessError("Такой тип расхода уже существует.")
            expense_type.name = name
        if "sort_order" in data:
            expense_type.sort_order = data["sort_order"]
        if "is_active" in data:
            expense_type.is_active = data["is_active"]

        expense_type.save()
        AuditService.log(
            user=actor,
            action=AuditLog.Action.UPDATE,
            entity_type="expense_type",
            entity_id=expense_type.id,
            old_value=old,
            new_value={"name": expense_type.name, "is_active": expense_type.is_active},
            ip_address=ip,
        )
        return expense_type

    @transaction.atomic
    def delete_type(self, *, actor, expense_type: ExpenseType, ip: str | None = None) -> None:
        if self.repository.is_used(expense_type):
            raise BusinessError("Тип расхода используется. Его можно отключить, но не удалить.")
        type_id = expense_type.id
        name = expense_type.name
        self.repository.delete(expense_type)
        AuditService.log(
            user=actor,
            action=AuditLog.Action.DELETE,
            entity_type="expense_type",
            entity_id=type_id,
            old_value={"name": name},
            ip_address=ip,
        )


class ExpenseService:
    def __init__(
        self,
        repository: ExpenseRepository | None = None,
        type_repository: ExpenseTypeRepository | None = None,
        event_service: DeliveryEventService | None = None,
    ) -> None:
        self.repository = repository or ExpenseRepository()
        self.types = type_repository or ExpenseTypeRepository()
        self.events = event_service or DeliveryEventService()

    def _get_type(self, type_id: int) -> ExpenseType:
        expense_type = self.types.get_by_id(type_id)
        if expense_type is None:
            raise BusinessError("Тип расхода не найден.")
        if not expense_type.is_active:
            raise BusinessError("Тип расхода отключён, выберите другой.")
        return expense_type

    @staticmethod
    def _resolve_payer(payer: str | None, amount, currency: str) -> tuple[str, bool]:
        """Плательщик берётся из формы; если не указан — применяется правило порога.

        Валюта расхода не совпала с валютой порога — берётся плательщик по умолчанию
        из тех же настроек, а не жёстко зашитая компания.
        """
        if payer:
            return payer, False

        settings = ExpenseSettings.load()
        if not settings.auto_payer_enabled:
            return Payer.COMPANY, False

        auto_payer, applied = settings.resolve_payer(amount, currency)
        if applied and auto_payer:
            return auto_payer, True
        # Правило включено, но неприменимо к этой валюте — плательщик по умолчанию
        return settings.payer_below, True

    @transaction.atomic
    def add_expense(self, *, actor, delivery: Delivery, data: dict, ip: str | None = None) -> Expense:
        # Расход добавляется на любом этапе живого рейса: до отправления, в пути,
        # после просрочки и после прибытия. Исключение — отменённый рейс.
        from apps.deliveries.models import DeliveryStatus

        if delivery.status == DeliveryStatus.CANCELLED:
            raise BusinessError("Рейс отменён — расходы по нему не добавляются.")

        expense_type = self._get_type(data["expense_type_id"])
        amount = data["amount"]
        currency = data.get("currency", "USD")
        payer, auto_assigned = self._resolve_payer(data.get("payer"), amount, currency)

        expense = Expense.objects.create(
            delivery=delivery,
            expense_type=expense_type,
            amount=amount,
            currency=currency,
            payer=payer,
            payer_auto_assigned=auto_assigned,
            description=data["description"].strip(),
            comment=(data.get("comment") or "").strip(),
            created_by=actor,
        )

        self.events.log(
            delivery=delivery,
            event_type=DeliveryEvent.EventType.EXPENSE_ADDED,
            user=actor,
            comment=expense.description,
            metadata={
                "expense_id": expense.id,
                "type": expense_type.name,
                "amount": str(amount),
                "currency": currency,
                "payer": payer,
            },
        )
        AuditService.log(
            user=actor,
            action=AuditLog.Action.CREATE,
            entity_type="expense",
            entity_id=expense.id,
            new_value={
                "delivery_id": delivery.id,
                "type": expense_type.name,
                "amount": str(amount),
                "currency": currency,
                "payer": payer,
            },
            ip_address=ip,
        )
        logger.info(
            "Расход %s %s добавлен к рейсу #%s сотрудником %s",
            amount, currency, delivery.id, actor.login,
        )
        return expense

    @transaction.atomic
    def update_expense(self, *, actor, expense: Expense, data: dict, ip: str | None = None) -> Expense:
        old = {
            "type": expense.expense_type.name,
            "amount": str(expense.amount),
            "currency": expense.currency,
            "payer": expense.payer,
            "description": expense.description,
        }

        if "expense_type_id" in data:
            expense.expense_type = self._get_type(data["expense_type_id"])
        if "amount" in data:
            expense.amount = data["amount"]
        if "currency" in data:
            expense.currency = data["currency"]
        if "payer" in data:
            expense.payer = data["payer"]
            expense.payer_auto_assigned = False
        elif expense.payer_auto_assigned and ("amount" in data or "currency" in data):
            # Плательщик был определён правилом порога, а правило зависит от суммы
            # и валюты: после их правки отметка «определён правилом» обязана
            # соответствовать действующему правилу.
            expense.payer, expense.payer_auto_assigned = self._resolve_payer(
                None, expense.amount, expense.currency
            )
        if "description" in data:
            expense.description = data["description"].strip()
        if "comment" in data:
            expense.comment = (data["comment"] or "").strip()

        expense.save()

        new = {
            "type": expense.expense_type.name,
            "amount": str(expense.amount),
            "currency": expense.currency,
            "payer": expense.payer,
            "description": expense.description,
        }
        self.events.log(
            delivery=expense.delivery,
            event_type=DeliveryEvent.EventType.EXPENSE_UPDATED,
            user=actor,
            comment=expense.description,
            metadata={"expense_id": expense.id, "old": old, "new": new},
        )
        AuditService.log(
            user=actor,
            action=AuditLog.Action.UPDATE,
            entity_type="expense",
            entity_id=expense.id,
            old_value=old,
            new_value=new,
            ip_address=ip,
        )
        return expense

    @transaction.atomic
    def delete_expense(self, *, actor, expense: Expense, ip: str | None = None) -> None:
        """Удаление расхода — операция администратора, след остаётся в истории."""
        snapshot = {
            "type": expense.expense_type.name,
            "amount": str(expense.amount),
            "currency": expense.currency,
            "payer": expense.payer,
            "description": expense.description,
            "created_by": expense.created_by.full_name,
        }
        delivery = expense.delivery
        expense_id = expense.id
        expense.delete()

        self.events.log(
            delivery=delivery,
            event_type=DeliveryEvent.EventType.EXPENSE_DELETED,
            user=actor,
            comment=snapshot["description"],
            metadata={"expense_id": expense_id, "deleted": snapshot},
        )
        AuditService.log(
            user=actor,
            action=AuditLog.Action.DELETE,
            entity_type="expense",
            entity_id=expense_id,
            old_value=snapshot,
            ip_address=ip,
        )
        logger.warning("Расход #%s удалён администратором %s", expense_id, actor.login)


class ExpenseSettingsService:
    @transaction.atomic
    def update(self, *, actor, data: dict, ip: str | None = None) -> ExpenseSettings:
        settings = ExpenseSettings.load()
        old = {
            "auto_payer_enabled": settings.auto_payer_enabled,
            "threshold_amount": str(settings.threshold_amount),
            "threshold_currency": settings.threshold_currency,
            "payer_above": settings.payer_above,
            "payer_below": settings.payer_below,
        }
        for field in (
            "auto_payer_enabled",
            "threshold_amount",
            "threshold_currency",
            "payer_above",
            "payer_below",
        ):
            if field in data:
                setattr(settings, field, data[field])
        settings.save()

        AuditService.log(
            user=actor,
            action=AuditLog.Action.UPDATE,
            entity_type="expense_settings",
            entity_id=settings.id,
            old_value=old,
            new_value={
                "auto_payer_enabled": settings.auto_payer_enabled,
                "threshold_amount": str(settings.threshold_amount),
                "threshold_currency": settings.threshold_currency,
                "payer_above": settings.payer_above,
                "payer_below": settings.payer_below,
            },
            ip_address=ip,
        )
        return settings
