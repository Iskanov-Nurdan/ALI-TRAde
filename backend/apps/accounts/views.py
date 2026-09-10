"""HTTP-слой сотрудников: только валидация ввода и вызов сервисов."""
import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from apps.accounts.filters import UserFilter
from apps.accounts.models import User
from apps.accounts.repositories import UserRepository
from apps.accounts.serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    SetActiveSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from apps.accounts.services import UserService
from apps.accounts.tokens import SessionRefreshSerializer, SessionVerifySerializer
from apps.core.models import AuditLog
from apps.core.permissions import IsAdmin
from apps.core.services import AuditService
from apps.core.utils import client_ip

logger = logging.getLogger(__name__)


class LoginView(TokenObtainPairView):
    """POST /api/auth/login/ — вход по логину и паролю.

    Частота ограничена: защита от перебора пароля.
    """

    serializer_class = LoginSerializer
    permission_classes = (AllowAny,)
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        """Успешный вход попадает в журнал: без этого компрометацию учётной
        записи по журналу не расследовать."""
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as error:
            raise InvalidToken(error.args[0])

        AuditService.log(
            user=serializer.user,
            action=AuditLog.Action.LOGIN,
            entity_type="user",
            entity_id=serializer.user.id,
            ip_address=client_ip(request),
        )
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class SessionRefreshView(TokenRefreshView):
    """POST /api/auth/refresh/ — обновление пары токенов."""

    serializer_class = SessionRefreshSerializer


class SessionVerifyView(TokenVerifyView):
    """POST /api/auth/verify/ — проверка, что сессия ещё жива."""

    serializer_class = SessionVerifySerializer


class MeView(APIView):
    """GET /api/auth/me/ — текущий пользователь."""

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class ChangePasswordView(APIView):
    """POST /api/auth/change-password/ — смена собственного пароля."""

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        UserService().change_own_password(
            user=request.user,
            current_password=serializer.validated_data["current_password"],
            new_password=serializer.validated_data["new_password"],
            ip=client_ip(request),
        )
        return Response({"detail": "Пароль изменён."})


class UserViewSet(viewsets.ModelViewSet):
    """CRUD сотрудников. Доступен только администратору."""

    serializer_class = UserSerializer
    permission_classes = (IsAdmin,)
    filterset_class = UserFilter
    ordering_fields = ("full_name", "created_at", "role")
    ordering = ("full_name",)
    search_fields = ("full_name", "login")

    def get_queryset(self):
        return UserRepository().get_queryset()

    def create(self, request, *args, **kwargs):
        serializer = UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = UserService().create_user(
            actor=request.user, data=serializer.validated_data, ip=client_ip(request)
        )
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance: User = self.get_object()
        serializer = UserUpdateSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        user = UserService().update_user(
            actor=request.user,
            user=instance,
            data=serializer.validated_data,
            ip=client_ip(request),
        )
        return Response(UserSerializer(user).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance: User = self.get_object()
        UserService().delete_user(actor=request.user, user=instance, ip=client_ip(request))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="set-active")
    def set_active(self, request, pk=None):
        """POST /api/users/{id}/set-active/ — блокировка и разблокировка."""
        instance: User = self.get_object()
        serializer = SetActiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = UserService().set_active(
            actor=request.user,
            user=instance,
            is_active=serializer.validated_data["is_active"],
            ip=client_ip(request),
        )
        return Response(UserSerializer(user).data)


class EmployeeDirectoryView(APIView):
    """GET /api/users/directory/ — краткий справочник активных сотрудников."""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        """Только имена: логины сотрудников наружу не отдаются."""
        from apps.accounts.serializers import UserDirectorySerializer

        employees = UserRepository().list_active().order_by("full_name")
        return Response(UserDirectorySerializer(employees, many=True).data)
