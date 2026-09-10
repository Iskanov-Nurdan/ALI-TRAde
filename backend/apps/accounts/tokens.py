"""Жизненный цикл JWT: отзыв токенов и предельный срок сессии.

Стандартный SimpleJWT проверяет только подпись и срок годности. Этого мало:
заблокированный или удалённый сотрудник, а также сотрудник со сменённым паролём
продолжали бы работать по ранее выданному токену. Здесь добавлены три правила:

* в токен кладётся отпечаток пароля — смена пароля обесценивает все выданные
  токены (и свои, и выданные администратором при сбросе);
* пользователь проверяется на каждом запросе: существует, не заблокирован;
* сессия имеет предельный срок: ротация refresh не может отодвинуть его дальше,
  чем на JWT_REFRESH_DAYS от момента входа.
"""
import hashlib

from django.contrib.auth import get_user_model
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer, TokenVerifySerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import UntypedToken

# Отпечаток пароля: меняется вместе с хешем пароля, поэтому старые токены
# перестают приниматься сразу после смены или сброса пароля.
PASSWORD_CLAIM = "pwd"
# Предельный момент окончания сессии — переносится при каждой ротации.
SESSION_EXPIRY_CLAIM = "ses"


def password_stamp(user) -> str:
    """Короткий отпечаток текущего хеша пароля."""
    return hashlib.sha256(user.password.encode("utf-8")).hexdigest()[:16]


def stamp_token(token, user):
    """Проставляет отпечаток пароля и предельный срок сессии."""
    token[PASSWORD_CLAIM] = password_stamp(user)
    token[SESSION_EXPIRY_CLAIM] = int(token.payload["exp"])
    return token


def resolve_user(payload: dict):
    """Пользователь токена либо 401.

    Единая точка проверки для аутентификации, обновления и проверки токена.
    """
    user_model = get_user_model()
    user_id = payload.get(api_settings.USER_ID_CLAIM)
    if user_id is None:
        raise InvalidToken("Токен не содержит идентификатор пользователя.")

    try:
        user = user_model.objects.get(**{api_settings.USER_ID_FIELD: user_id})
    except (user_model.DoesNotExist, ValueError, TypeError):
        # Удалённая учётная запись — это 401, а не внутренняя ошибка сервера.
        raise AuthenticationFailed("Учётная запись не найдена.", "user_not_found")

    if not user.is_active:
        raise AuthenticationFailed("Учётная запись заблокирована.", "user_inactive")

    if payload.get(PASSWORD_CLAIM) != password_stamp(user):
        raise AuthenticationFailed("Пароль изменён, войдите заново.", "password_changed")

    return user


class SessionJWTAuthentication(JWTAuthentication):
    """Аутентификация с проверкой состояния учётной записи на каждом запросе."""

    def get_user(self, validated_token):
        return resolve_user(validated_token.payload)


class SessionRefreshSerializer(TokenRefreshSerializer):
    """Обновление пары токенов с проверкой пользователя и предела сессии."""

    def validate(self, attrs):
        try:
            refresh = self.token_class(attrs["refresh"])
        except TokenError as error:
            raise InvalidToken(str(error))

        resolve_user(refresh.payload)
        session_end = refresh.payload.get(SESSION_EXPIRY_CLAIM)

        data = {"access": str(refresh.access_token)}

        if api_settings.ROTATE_REFRESH_TOKENS:
            if api_settings.BLACKLIST_AFTER_ROTATION:
                try:
                    refresh.blacklist()
                except AttributeError:
                    pass

            refresh.set_jti()
            refresh.set_exp()
            refresh.set_iat()
            # Ротация выдаёт новый срок «сейчас + REFRESH_TOKEN_LIFETIME». Без
            # ограничения сессию можно было бы продлевать бесконечно, дёргая
            # обновление раз в неделю.
            if session_end is not None:
                refresh.payload["exp"] = min(int(refresh.payload["exp"]), int(session_end))
            data["refresh"] = str(refresh)

        return data


class SessionVerifySerializer(TokenVerifySerializer):
    """Проверка токена с учётом состояния учётной записи."""

    def validate(self, attrs):
        data = super().validate(attrs)
        # Подпись и срок проверены родителем, остаётся состояние пользователя:
        # заблокированному сотруднику «сессия жива» отвечать нельзя.
        resolve_user(UntypedToken(attrs["token"]).payload)
        return data
