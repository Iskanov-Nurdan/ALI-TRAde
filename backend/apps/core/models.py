from django.db import models


class TimeStampedModel(models.Model):
    """Базовая модель с датами создания и обновления."""

    created_at = models.DateTimeField("Создано", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        abstract = True


class AuditLog(models.Model):
    """Журнал административных и значимых действий пользователей."""

    class Action(models.TextChoices):
        CREATE = "CREATE", "Создание"
        UPDATE = "UPDATE", "Изменение"
        DELETE = "DELETE", "Удаление"
        LOGIN = "LOGIN", "Вход в систему"
        BLOCK = "BLOCK", "Блокировка"
        UNBLOCK = "UNBLOCK", "Разблокировка"

    user = models.ForeignKey(
        "accounts.User",
        verbose_name="Пользователь",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField("Действие", max_length=20, choices=Action.choices)
    entity_type = models.CharField("Тип объекта", max_length=50, db_index=True)
    entity_id = models.CharField("ID объекта", max_length=50, db_index=True)
    old_value = models.JSONField("Было", null=True, blank=True)
    new_value = models.JSONField("Стало", null=True, blank=True)
    ip_address = models.GenericIPAddressField("IP-адрес", null=True, blank=True)
    created_at = models.DateTimeField("Дата", auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_logs"
        verbose_name = "Запись аудита"
        verbose_name_plural = "Журнал аудита"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def __str__(self) -> str:
        return f"{self.get_action_display()} {self.entity_type}#{self.entity_id}"
