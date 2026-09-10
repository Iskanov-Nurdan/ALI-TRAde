import re

from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel

# Кириллические буквы, визуально совпадающие с латинскими: «01 КГ» и «01 KG» —
# это одна и та же машина, поиск обязан находить оба написания.
CYRILLIC_TO_LATIN = str.maketrans(
    {
        "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
        "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X", "І": "I", "Ѕ": "S",
        "Г": "G", "Д": "D", "Ж": "J", "З": "Z", "И": "I", "Л": "L", "П": "P",
        "Ф": "F", "Ц": "C", "Ч": "C", "Ш": "S", "Щ": "S", "Ы": "Y", "Э": "E",
        "Ю": "U", "Я": "Q", "Б": "B", "Й": "I", "Ь": "", "Ъ": "", "Ё": "E",
    }
)


def normalize_vehicle_number(value: str) -> str:
    """Приводит номер к виду для поиска: '01 КГ 1234 АВ' -> '01KG1234AB'."""
    upper = (value or "").upper().translate(CYRILLIC_TO_LATIN)
    return re.sub(r"[^0-9A-Z]", "", upper)


class DeliveryStatus(models.TextChoices):
    CREATED = "CREATED", "Создан"
    IN_TRANSIT = "IN_TRANSIT", "В пути"
    ARRIVED = "ARRIVED", "Прибыл"
    CANCELLED = "CANCELLED", "Отменён"


class DeliveryColor(models.TextChoices):
    """Цвет рассчитывается на лету и в базе не хранится."""

    NORMAL = "NORMAL", "Обычный"
    ORANGE = "ORANGE", "Есть расход"
    RED = "RED", "Просрочен"


class Delivery(TimeStampedModel):
    """Рейс: движение машины между двумя точками."""

    point_from = models.ForeignKey(
        "points.Point",
        verbose_name="Точка отправления",
        on_delete=models.PROTECT,
        related_name="departures",
    )
    point_to = models.ForeignKey(
        "points.Point",
        verbose_name="Точка прибытия",
        on_delete=models.PROTECT,
        related_name="arrivals",
    )
    vehicle_number = models.CharField("Номер машины", max_length=30, db_index=True)
    vehicle_number_search = models.CharField(
        "Номер для поиска", max_length=30, db_index=True, editable=False
    )

    created_by = models.ForeignKey(
        "accounts.User",
        verbose_name="Создал",
        on_delete=models.PROTECT,
        related_name="created_deliveries",
    )
    dispatched_by = models.ForeignKey(
        "accounts.User",
        verbose_name="Отправил",
        on_delete=models.PROTECT,
        related_name="dispatched_deliveries",
        null=True,
        blank=True,
    )
    received_by = models.ForeignKey(
        "accounts.User",
        verbose_name="Принял",
        on_delete=models.PROTECT,
        related_name="received_deliveries",
        null=True,
        blank=True,
    )
    cancelled_by = models.ForeignKey(
        "accounts.User",
        verbose_name="Отменил",
        on_delete=models.PROTECT,
        related_name="cancelled_deliveries",
        null=True,
        blank=True,
    )

    dispatched_at = models.DateTimeField("Время отправления", db_index=True)
    deadline_at = models.DateTimeField("Плановое прибытие", db_index=True)
    received_at = models.DateTimeField("Фактическое прибытие", null=True, blank=True, db_index=True)
    cancelled_at = models.DateTimeField("Время отмены", null=True, blank=True)
    planned_duration_minutes = models.PositiveIntegerField(
        "Плановая длительность, мин", null=True, blank=True
    )

    status = models.CharField(
        "Статус", max_length=12, choices=DeliveryStatus.choices,
        default=DeliveryStatus.CREATED, db_index=True,
    )
    dispatch_comment = models.TextField("Комментарий при отправлении", blank=True)
    receive_comment = models.TextField("Комментарий при приёме", blank=True)
    cancel_comment = models.TextField("Причина отмены", blank=True)
    deadline_passed_logged = models.BooleanField(
        "Просрочка зафиксирована в истории", default=False, editable=False
    )

    class Meta:
        db_table = "deliveries"
        verbose_name = "Рейс"
        verbose_name_plural = "Рейсы"
        ordering = ("-dispatched_at", "-id")
        indexes = [
            models.Index(fields=["status", "deadline_at"]),
            models.Index(fields=["vehicle_number_search", "-dispatched_at"]),
        ]

    def __str__(self):
        return f"Рейс #{self.pk} — {self.vehicle_number}"

    def save(self, *args, **kwargs):
        self.vehicle_number = (self.vehicle_number or "").strip().upper()
        self.vehicle_number_search = normalize_vehicle_number(self.vehicle_number)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "vehicle_number" in update_fields:
            kwargs["update_fields"] = list(set(update_fields) | {"vehicle_number_search"})
        super().save(*args, **kwargs)

    # --- Вычисляемые характеристики состояния ---

    @property
    def is_overdue(self) -> bool:
        """Машина в пути, а плановое время прибытия уже прошло."""
        return self.status == DeliveryStatus.IN_TRANSIT and timezone.now() > self.deadline_at

    @property
    def late_minutes(self) -> int:
        """Опоздание в минутах: по факту прибытия либо по текущему моменту."""
        if self.status == DeliveryStatus.ARRIVED and self.received_at:
            delta = self.received_at - self.deadline_at
        elif self.status == DeliveryStatus.IN_TRANSIT:
            delta = timezone.now() - self.deadline_at
        else:
            return 0
        seconds = delta.total_seconds()
        if seconds <= 0:
            return 0
        # Опоздание меньше минуты — всё равно опоздание: arrived_late уже True,
        # и величина не должна оставаться нулевой, иначе её не видно ни в
        # карточке, ни в выгрузке.
        return max(int(seconds // 60), 1)

    @property
    def arrived_late(self) -> bool:
        return bool(
            self.status == DeliveryStatus.ARRIVED
            and self.received_at
            and self.received_at > self.deadline_at
        )

    @property
    def route_points(self) -> list[str]:
        """Полная цепочка маршрута: отправление, промежуточные точки, прибытие."""
        middle = [waypoint.point.name for waypoint in self.waypoints.all()]
        return [self.point_from.name, *middle, self.point_to.name]

    @property
    def state_label(self) -> str:
        if self.status == DeliveryStatus.ARRIVED:
            return "Прибыл с опозданием" if self.arrived_late else "Прибыл вовремя"
        if self.is_overdue:
            return "Просрочен"
        return self.get_status_display()

    def color(self, has_expenses: bool) -> str:
        """Красный (просрочка) важнее оранжевого (расход)."""
        if self.is_overdue:
            return DeliveryColor.RED
        if has_expenses:
            return DeliveryColor.ORANGE
        return DeliveryColor.NORMAL


class DeliveryEvent(models.Model):
    """История действий по рейсу. Записи не редактируются и не удаляются."""

    class EventType(models.TextChoices):
        CREATED = "CREATED", "Рейс создан"
        DISPATCHED = "DISPATCHED", "Машина отправлена"
        EXPENSE_ADDED = "EXPENSE_ADDED", "Добавлен расход"
        EXPENSE_UPDATED = "EXPENSE_UPDATED", "Изменён расход"
        EXPENSE_DELETED = "EXPENSE_DELETED", "Удалён расход"
        DEADLINE_PASSED = "DEADLINE_PASSED", "Срок прибытия истёк"
        WAYPOINT_PASSED = "WAYPOINT_PASSED", "Пройдена промежуточная точка"
        RECEIVED = "RECEIVED", "Прибытие подтверждено"
        CANCELLED = "CANCELLED", "Рейс отменён"
        COMMENT_ADDED = "COMMENT_ADDED", "Добавлен комментарий"
        UPDATED = "UPDATED", "Рейс изменён"

    delivery = models.ForeignKey(
        Delivery, verbose_name="Рейс", on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField("Тип события", max_length=20, choices=EventType.choices)
    user = models.ForeignKey(
        "accounts.User",
        verbose_name="Сотрудник",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_events",
    )
    event_time = models.DateTimeField("Время события", default=timezone.now, db_index=True)
    comment = models.TextField("Комментарий", blank=True)
    metadata = models.JSONField("Доп. данные", null=True, blank=True)

    class Meta:
        db_table = "delivery_events"
        verbose_name = "Событие рейса"
        verbose_name_plural = "История рейсов"
        ordering = ("event_time", "id")

    def __str__(self):
        return f"{self.get_event_type_display()} — рейс #{self.delivery_id}"


class DeliveryWaypoint(models.Model):
    """Промежуточная точка маршрута: граница, склад, перегруз и т.п."""

    delivery = models.ForeignKey(
        Delivery, verbose_name="Рейс", on_delete=models.CASCADE, related_name="waypoints"
    )
    point = models.ForeignKey(
        "points.Point", verbose_name="Точка", on_delete=models.PROTECT, related_name="waypoints"
    )
    order = models.PositiveSmallIntegerField("Порядок в маршруте", default=0)
    passed_at = models.DateTimeField("Время прохождения", null=True, blank=True)
    passed_by = models.ForeignKey(
        "accounts.User",
        verbose_name="Отметил прохождение",
        on_delete=models.PROTECT,
        related_name="passed_waypoints",
        null=True,
        blank=True,
    )
    comment = models.TextField("Комментарий", blank=True)

    class Meta:
        db_table = "delivery_waypoints"
        verbose_name = "Промежуточная точка"
        verbose_name_plural = "Промежуточные точки"
        ordering = ("order", "id")
        constraints = [
            models.UniqueConstraint(fields=["delivery", "point"], name="uniq_waypoint_point_per_delivery"),
        ]

    def __str__(self):
        return f"{self.point} (рейс #{self.delivery_id})"

    @property
    def is_passed(self) -> bool:
        return self.passed_at is not None
