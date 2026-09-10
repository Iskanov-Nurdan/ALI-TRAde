"""Курсы валют и пересчёт разновалютных сумм в сомы."""
import logging
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from apps.core.exceptions import BusinessError
from apps.core.models import AuditLog
from apps.core.services import AuditService
from apps.expenses.models import Currency, CurrencyRate

logger = logging.getLogger(__name__)

BASE_CURRENCY = Currency.KGS

# Ориентировочные значения на момент запуска — администратор правит их в разделе
# «Курсы валют», система лишь не оставляет справочник пустым.
DEFAULT_RATES = {
    Currency.KGS: Decimal("1"),
    Currency.USD: Decimal("87.5"),
}


class CurrencyRateService:
    """Чтение и обновление курсов, пересчёт итогов в базовую валюту."""

    @staticmethod
    def ensure_defaults() -> None:
        """Создаёт недостающие валюты в справочнике."""
        existing = set(CurrencyRate.objects.values_list("code", flat=True))
        missing = [
            CurrencyRate(code=code, rate=rate)
            for code, rate in DEFAULT_RATES.items()
            if code not in existing
        ]
        if missing:
            CurrencyRate.objects.bulk_create(missing)

    @classmethod
    def all_rates(cls) -> dict[str, Decimal]:
        """Все курсы одной выборкой.

        Справочник читается целиком, и недостающие валюты добавляются по факту:
        отдельная проверка ensure_defaults() удваивала бы число запросов, а курсы
        запрашиваются на каждый список рейсов.
        """
        rates = dict(CurrencyRate.objects.values_list("code", "rate"))
        missing = {code: rate for code, rate in DEFAULT_RATES.items() if code not in rates}
        if missing:
            CurrencyRate.objects.bulk_create(
                [CurrencyRate(code=code, rate=rate) for code, rate in missing.items()]
            )
            rates.update(missing)
        rates[BASE_CURRENCY] = Decimal("1")
        return rates

    @classmethod
    def list_rates(cls) -> list[CurrencyRate]:
        cls.ensure_defaults()
        return list(CurrencyRate.objects.select_related("updated_by").order_by("code"))

    @classmethod
    def convert(cls, amount, currency: str, rates: dict | None = None) -> Decimal:
        """Переводит сумму в сомы по текущему курсу."""
        rate = (rates if rates is not None else cls.all_rates()).get(currency)
        if rate is None:
            return Decimal("0")
        return (Decimal(amount) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @classmethod
    def convert_totals(cls, totals: dict, rates: dict | None = None) -> dict:
        """Сводит суммы по валютам в одну сумму в сомах.

        Возвращает саму сумму и список валют без курса — их пересчитать нельзя,
        и интерфейс должен об этом сказать, а не молча занижать итог.

        Курсы можно передать снаружи: в списке из сотни рейсов они одинаковы для
        всех строк, и читать справочник на каждую строку незачем.
        """
        rates = cls.all_rates() if rates is None else rates
        total = Decimal("0")
        missing = []
        for currency, amount in (totals or {}).items():
            rate = rates.get(currency)
            if rate is None:
                missing.append(currency)
                continue
            total += Decimal(str(amount)) * rate
        return {
            "currency": BASE_CURRENCY,
            "amount": str(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "missing_rates": missing,
        }

    @classmethod
    @transaction.atomic
    def update_rates(cls, *, actor, rates: dict, ip: str | None = None) -> list[CurrencyRate]:
        cls.ensure_defaults()
        current = {item.code: item for item in CurrencyRate.objects.select_for_update()}

        changed = {}
        for code, value in rates.items():
            if code == BASE_CURRENCY:
                # Сом — базовая валюта, его курс всегда единица
                continue
            item = current.get(code)
            if item is None:
                raise BusinessError(f"Неизвестная валюта: {code}.")
            new_rate = Decimal(str(value))
            if new_rate <= 0:
                raise BusinessError("Курс должен быть больше нуля.")
            if item.rate != new_rate:
                changed[code] = {"было": str(item.rate), "стало": str(new_rate)}
                item.rate = new_rate
                item.updated_by = actor
                item.save(update_fields=["rate", "updated_by", "updated_at"])

        if changed:
            AuditService.log(
                user=actor,
                action=AuditLog.Action.UPDATE,
                entity_type="currency_rate",
                entity_id="all",
                new_value=changed,
                ip_address=ip,
            )
            logger.info("Курсы валют обновлены сотрудником %s: %s", actor.login, ", ".join(changed))

        return cls.list_rates()
