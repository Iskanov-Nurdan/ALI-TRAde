"""Базовый репозиторий: единственный слой, который знает про ORM-запросы."""
from collections.abc import Iterable
from typing import Any, Generic, TypeVar

from django.core.exceptions import ValidationError
from django.db.models import Model, QuerySet

from apps.core.exceptions import NotFoundError

M = TypeVar("M", bound=Model)


class BaseRepository(Generic[M]):
    model: type[M]

    def get_queryset(self) -> QuerySet[M]:
        return self.model._default_manager.all()

    def get_by_id(self, obj_id) -> M | None:
        """Некорректный идентификатор — это «не найдено», а не ошибка сервера."""
        try:
            return self.get_queryset().filter(pk=obj_id).first()
        except (ValueError, TypeError, ValidationError):
            return None

    def get_or_fail(self, obj_id: int) -> M:
        obj = self.get_by_id(obj_id)
        if obj is None:
            raise NotFoundError(f"Запись #{obj_id} не найдена.")
        return obj

    def exists(self, **filters: Any) -> bool:
        return self.get_queryset().filter(**filters).exists()

    def create(self, **data: Any) -> M:
        return self.model._default_manager.create(**data)

    def update(self, instance: M, **data: Any) -> M:
        for field, value in data.items():
            setattr(instance, field, value)
        instance.save(update_fields=self._update_fields(instance, data))
        return instance

    def delete(self, instance: M) -> None:
        instance.delete()

    @staticmethod
    def _update_fields(instance: M, data: dict[str, Any]) -> Iterable[str] | None:
        fields = set(data.keys())
        if any(f.name == "updated_at" for f in instance._meta.get_fields()):
            fields.add("updated_at")
        return list(fields) or None
