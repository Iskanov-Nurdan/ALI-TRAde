from django.db.models import QuerySet

from apps.accounts.models import User, UserRole
from apps.core.repositories import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def get_queryset(self) -> QuerySet[User]:
        """Удалённые сотрудники не показываются нигде, но остаются в истории."""
        return super().get_queryset().filter(deleted_at__isnull=True)

    def get_by_login(self, login: str) -> User | None:
        return self.get_queryset().filter(login=login.strip().lower()).first()

    def login_exists(self, login: str, exclude_id: int | None = None) -> bool:
        qs = self.get_queryset().filter(login=login.strip().lower())
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)
        return qs.exists()

    def list_active(self) -> QuerySet[User]:
        return self.get_queryset().filter(is_active=True)

    def count_active_admins(self, exclude_id: int | None = None) -> int:
        qs = self.get_queryset().filter(role=UserRole.ADMIN, is_active=True)
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)
        return qs.count()
