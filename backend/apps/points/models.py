from django.db import models

from apps.core.models import TimeStampedModel


class Point(TimeStampedModel):
    """Точка маршрута: город, склад, граница и т.п."""

    name = models.CharField("Название", max_length=120, unique=True)
    address = models.CharField("Адрес", max_length=255, blank=True)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    description = models.TextField("Описание", blank=True)
    is_active = models.BooleanField("Активна", default=True, db_index=True)

    class Meta:
        db_table = "points"
        verbose_name = "Точка"
        verbose_name_plural = "Точки"
        ordering = ("name",)

    def __str__(self):
        return self.name
