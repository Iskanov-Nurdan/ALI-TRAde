from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.accounts.models import User, UserRole
from apps.accounts.tokens import stamp_token
from apps.core.validators import plain_text


class UserSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "full_name",
            "short_name",
            "login",
            "phone",
            "role",
            "role_display",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class UserShortSerializer(serializers.ModelSerializer):
    """Компактное представление сотрудника для вложенных объектов.

    Без логина: этот сериализатор подставляется в списки рейсов, расходов и
    истории, доступные любому сотруднику, а логин — половина пары для подбора
    пароля. Полные учётные данные отдаёт только UserSerializer в разделе
    администратора.
    """

    class Meta:
        model = User
        fields = ("id", "full_name", "short_name")
        read_only_fields = fields


class UserDirectorySerializer(serializers.ModelSerializer):
    """Справочник для фильтров: имя без логина и прочих учётных данных."""

    class Meta:
        model = User
        fields = ("id", "full_name", "short_name")
        read_only_fields = fields


def validate_full_name(value: str) -> str:
    """ФИО отдаётся во всех вложенных объектах (created_by, dispatched_by и др.)."""
    value = plain_text(value).strip()
    if len(value) < 3:
        raise serializers.ValidationError("Укажите полное имя сотрудника.")
    return value


class UserCreateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150)
    login = serializers.RegexField(r"^[a-zA-Z0-9_.\-]{3,60}$", max_length=60)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    password = serializers.CharField(min_length=6, max_length=128, write_only=True)
    role = serializers.ChoiceField(choices=UserRole.choices, default=UserRole.EMPLOYEE)
    is_active = serializers.BooleanField(default=True)

    def validate_full_name(self, value: str) -> str:
        return validate_full_name(value)


class UserUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150, required=False)
    login = serializers.RegexField(r"^[a-zA-Z0-9_.\-]{3,60}$", max_length=60, required=False)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    password = serializers.CharField(min_length=6, max_length=128, required=False, write_only=True)
    role = serializers.ChoiceField(choices=UserRole.choices, required=False)
    is_active = serializers.BooleanField(required=False)

    def validate_full_name(self, value: str) -> str:
        return validate_full_name(value)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Не переданы поля для изменения.")
        return attrs


class SetActiveSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(min_length=6, max_length=128, write_only=True)

    def validate_new_password(self, value: str) -> str:
        validate_password(value)
        return value


class LoginSerializer(TokenObtainPairSerializer):
    """JWT-логин по полю login с расширенными данными пользователя."""

    username_field = User.USERNAME_FIELD

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["full_name"] = user.full_name
        # Отпечаток пароля и предел сессии: см. apps/accounts/tokens.py
        return stamp_token(token, user)

    def validate(self, attrs):
        attrs[self.username_field] = attrs.get(self.username_field, "").strip().lower()
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data
