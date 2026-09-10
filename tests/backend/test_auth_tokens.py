# -*- coding: utf-8 -*-
"""Атака на жизненный цикл JWT.

SIMPLE_JWT настроен с ROTATE_REFRESH_TOKENS=True и BLACKLIST_AFTER_ROTATION=False,
приложение rest_framework_simplejwt.token_blacklist не установлено, эндпоинта
выхода нет. Итог: выданный refresh-токен нельзя отозвать вообще ничем.
"""
from datetime import timedelta
from unittest import mock

import jwt
from rest_framework.test import APIClient
from rest_framework_simplejwt.utils import aware_utcnow

from apps.accounts.models import User

from .base import PASSWORD, AdversarialBase


def exp_of(token: str) -> int:
    return jwt.decode(token, options={"verify_signature": False})["exp"]


class RefreshTokenRevocation(AdversarialBase):
    def test_rotated_refresh_token_must_stop_working(self):
        """Старый refresh обязан умирать после ротации.

        Ротация включена, но чёрного списка нет: украденный refresh можно
        предъявлять сколько угодно раз и получать новые пары токенов.
        """
        client = APIClient()
        stolen = self.login(self.employee.login, client=client).data["refresh"]

        first = client.post("/api/auth/refresh/", {"refresh": stolen}, format="json")
        self.assertEqual(first.status_code, 200, "первая ротация должна проходить")

        replay = client.post("/api/auth/refresh/", {"refresh": stolen}, format="json")

        self.assertEqual(
            replay.status_code,
            401,
            "уже использованный refresh-токен принят повторно — отозвать сессию нечем",
        )

    def test_password_change_must_revoke_old_tokens(self):
        """Смена собственного пароля обязана обесценивать старые токены.

        Сейчас после смены пароля и старый access, и старый refresh продолжают
        работать — компрометацию учётной записи закрыть нечем.
        """
        client = APIClient()
        tokens = self.login(self.employee.login, client=client).data
        old_access, old_refresh = tokens["access"], tokens["refresh"]

        authed = APIClient()
        authed.credentials(HTTP_AUTHORIZATION="Bearer " + old_access)
        changed = authed.post(
            "/api/auth/change-password/",
            {"current_password": PASSWORD, "new_password": "totallyNew99"},
            format="json",
        )
        self.assertEqual(changed.status_code, 200)

        refreshed = APIClient().post(
            "/api/auth/refresh/", {"refresh": old_refresh}, format="json"
        )
        still_authorized = authed.get("/api/auth/me/")

        self.assertEqual(
            (refreshed.status_code, still_authorized.status_code),
            (401, 401),
            "после смены пароля старые токены обязаны перестать действовать",
        )

    def test_admin_password_reset_must_revoke_employee_tokens(self):
        """Сброс пароля администратором не выкидывает сотрудника из системы.

        Это основной сценарий реагирования на инцидент: администратор меняет
        пароль скомпрометированной учётке, а её токен продолжает работать.
        """
        client = APIClient()
        old_refresh = self.login(self.employee.login, client=client).data["refresh"]

        self.auth(self.admin)
        reset = self.client.patch(
            f"/api/users/{self.employee.id}/", {"password": "adminReset123"}, format="json"
        )
        self.assertEqual(reset.status_code, 200)

        refreshed = APIClient().post(
            "/api/auth/refresh/", {"refresh": old_refresh}, format="json"
        )

        self.assertEqual(
            refreshed.status_code,
            401,
            "после админского сброса пароля refresh сотрудника обязан быть недействителен",
        )

    def test_refresh_lifetime_must_not_slide_indefinitely(self):
        """Ротация продлевает срок жизни refresh, делая сессию бесконечной.

        JWT_REFRESH_DAYS=7 задумывался как предел, но каждая ротация выдаёт
        новый refresh со сроком «сейчас + 7 дней». Достаточно раз в неделю
        дёрнуть /api/auth/refresh/, чтобы сессия не кончалась никогда.
        """
        client = APIClient()
        token = self.login(self.employee.login, client=client).data["refresh"]
        original_exp = exp_of(token)

        almost_expired = aware_utcnow() + timedelta(days=6)
        with mock.patch(
            "rest_framework_simplejwt.tokens.aware_utcnow", return_value=almost_expired
        ):
            rotated = client.post("/api/auth/refresh/", {"refresh": token}, format="json")

        self.assertEqual(rotated.status_code, 200)
        new_exp = exp_of(rotated.data["refresh"])
        self.assertLessEqual(
            new_exp,
            original_exp,
            f"срок жизни refresh продлён на {(new_exp - original_exp) / 86400:.1f} суток "
            "сверх исходного — сессию нельзя завершить по времени",
        )


class DeletedUserRefresh(AdversarialBase):
    def test_refresh_of_deleted_user_must_not_return_500(self):
        """Удалили сотрудника — его вкладка роняет сервер.

        TokenRefreshSerializer делает User.objects.get(...) без обработки
        DoesNotExist, ошибка доходит до api_exception_handler и превращается
        в 500 «Внутренняя ошибка сервера» вместо честного 401.
        """
        client = APIClient()
        refresh = self.login(self.employee.login, client=client).data["refresh"]
        User.objects.filter(pk=self.employee.pk).delete()

        response = client.post("/api/auth/refresh/", {"refresh": refresh}, format="json")

        self.assertEqual(
            response.status_code,
            401,
            f"обновление токена удалённого пользователя вернуло {response.status_code}",
        )


class TokenVerifyIgnoresUserState(AdversarialBase):
    def test_verify_must_reject_token_of_blocked_user(self):
        """/api/auth/verify/ подтверждает токен заблокированного сотрудника.

        Фронтенд использует verify как проверку «сессия ещё жива», и получает
        «жива» для учётки, которую администратор только что заблокировал.
        """
        client = APIClient()
        access = self.login(self.employee.login, client=client).data["access"]
        self.employee.is_active = False
        self.employee.save(update_fields=["is_active"])

        response = client.post("/api/auth/verify/", {"token": access}, format="json")

        self.assertEqual(
            response.status_code,
            401,
            "verify подтвердил токен заблокированного пользователя",
        )
