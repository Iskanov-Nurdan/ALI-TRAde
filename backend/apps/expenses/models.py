from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel


class Currency(models.TextChoices):
    """Рабочие валюты компании: расчёты ведутся в долларах и сомах."""

    USD = "USD", "Доллар США"
    KGS = "KGS", "Сом"


class Payer(models.TextChoices):
    COMPANY = "COMPANY", "Наша компания"
    CHINA = "CHINA", "Китай"
    DRIVER = "DRIVER", "Водитель"
    OTHER = "OTHER", "Другое"


class ExpenseType(TimeStampedModel):
    """Справочник типов расходов — расширяется администратором без правки кода."""

    code = models.SlugField("Код", max_length=40, unique=True)
    name = models.CharField("Название", max_length=120, unique=True)
    sort_order = models.PositiveSmallIntegerField("Порядок", default=100)
    is_active = models.BooleanField("Активен", default=True, db_index=True)

    class Meta:
        db_table = "expense_types"
        verbose_name = "Тип расхода"
        verbose_name_plural = "Типы расходов"
        ordering = ("sort_order", "name")

    def __str__(self):
        return self.name


class Expense(models.Model):
    """Расход, привязанный к конкретному рейсу."""

    delivery = models.ForeignKey(
        "deliveries.Delivery",
        verbose_name="Рейс",
        on_delete=models.CASCADE,
        related_name="expenses",
    )
    expense_type = models.ForeignKey(
        ExpenseType,
        verbose_name="Тип расхода",
        on_delete=models.PROTECT,
        related_name="expenses",
    )
    amount = models.DecimalField(
        "Сумма", max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    currency = models.CharField(
        "Валюта", max_length=3, choices=Currency.choices, default=Currency.USD, db_index=True
    )
    payer = models.CharField(
        "Плательщик", max_length=10, choices=Payer.choices, default=Payer.COMPANY, db_index=True
    )
    payer_auto_assigned = models.BooleanField("Плательщик определён правилом", default=False)
    description = models.CharField("Описание расхода", max_length=255)
    comment = models.TextField("Комментарий", blank=True)
    created_by = models.ForeignKey(
        "accounts.User",
        verbose_name="Добавил",
        on_delete=models.PROTECT,
        related_name="created_expenses",
    )
    created_at = models.DateTimeField("Дата добавления", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        db_table = "expenses"
        verbose_name = "Расход"
        verbose_name_plural = "Расходы"
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=["delivery", "-created_at"])]

    def __str__(self):
        return f"{self.expense_type} — {self.amount} {self.currency}"


class ExpenseSettings(models.Model):
    """Настройка правила автоматического определения плательщика (singleton)."""

    auto_payer_enabled = models.BooleanField("Правило включено", default=False)
    threshold_amount = models.DecimalField(
        "Порог суммы", max_digits=12, decimal_places=2, default=50
    )
    threshold_currency = models.CharField(
        "Валюта порога", max_length=3, choices=Currency.choices, default=Currency.USD
    )
    payer_above = models.CharField(
        "Плательщик при превышении порога", max_length=10, choices=Payer.choices, default=Payer.CHINA
    )
    payer_below = models.CharField(
        "Плательщик до порога", max_length=10, choices=Payer.choices, default=Payer.COMPANY
    )
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        db_table = "expense_settings"
        verbose_name = "Настройки расходов"
        verbose_name_plural = "Настройки расходов"

    def __str__(self):
        return "Настройки расходов"

    @classmethod
    def load(cls) -> "ExpenseSettings":
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj

    def resolve_payer(self, amount, currency: str) -> tuple[str, bool]:
        """Возвращает (плательщик, был_ли_определён_автоматически)."""
        if not self.auto_payer_enabled or currency != self.threshold_currency:
            return "", False
        payer = self.payer_above if amount > self.threshold_amount else self.payer_below
        return payer, True


class CurrencyRate(TimeStampedModel):
    """Курс валюты к сому: сколько сомов стоит одна единица валюты.

    Нужен, чтобы сводить расходы в разных валютах к одной сумме. Сам сом
    хранится с курсом 1 и не редактируется.
    """

    BASE = Currency.KGS

    code = models.CharField("Валюта", max_length=3, choices=Currency.choices, unique=True)
    rate = models.DecimalField(
        "Курс к сому",
        max_digits=14,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    updated_by = models.ForeignKey(
        "accounts.User",
        verbose_name="Обновил",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_rates",
    )

    class Meta:
        db_table = "currency_rates"
        verbose_name = "Курс валюты"
        verbose_name_plural = "Курсы валют"
        ordering = ("code",)

    def __str__(self):
        return f"1 {self.code} = {self.rate} {self.BASE}"

    @property
    def is_base(self) -> bool:
        return self.code == self.BASE
