from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from apps.core.models import TimeStampedModel


class UserRole(models.TextChoices):
    ADMIN = "ADMIN", "Администратор"
    EMPLOYEE = "EMPLOYEE", "Сотрудник"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, login, password, **extra_fields):
        if not login:
            raise ValueError("Логин обязателен.")
        login = login.strip().lower()
        extra_fields.setdefault("role", UserRole.EMPLOYEE)
        user = self.model(login=login, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, login, password, **extra_fields):
        extra_fields.setdefault("role", UserRole.ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("full_name", login)
        if extra_fields.get("role") != UserRole.ADMIN:
            raise ValueError("Суперпользователь должен иметь роль ADMIN.")
        return self.create_user(login, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """Сотрудник системы. Роли: администратор и обычный сотрудник."""

    password = models.CharField("Хеш пароля", max_length=128, db_column="password_hash")
    full_name = models.CharField("ФИО", max_length=150)
    login = models.CharField("Логин", max_length=60, unique=True, db_index=True)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    role = models.CharField("Роль", max_length=10, choices=UserRole.choices, default=UserRole.EMPLOYEE)
    is_active = models.BooleanField("Активен", default=True, db_index=True)
    is_staff = models.BooleanField("Доступ в админку", default=False)
    # Удаление сотрудника делается мягким: строки журнала аудита и истории рейсов
    # ссылаются на него через SET_NULL, и физическое удаление обезличило бы уже
    # записанные действия.
    deleted_at = models.DateTimeField("Удалён", null=True, blank=True, db_index=True)

    objects = UserManager()

    USERNAME_FIELD = "login"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "users"
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"
        ordering = ("full_name",)

    def __str__(self):
        return f"{self.full_name} ({self.login})"

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def short_name(self) -> str:
        parts = self.full_name.split()
        if len(parts) >= 2:
            return f"{parts[0]} {parts[1][0]}."
        return self.full_name
