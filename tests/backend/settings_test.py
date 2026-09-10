"""Настройки только для адверсариального прогона.

Исходные настройки проекта (backend/config/settings.py) не меняются: здесь они
импортируются целиком, а поверх принудительно ставится SQLite в памяти, чтобы
тесты не зависели от Postgres из docker-compose.
"""
from config.settings import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "TEST": {"NAME": ":memory:"},
    }
}

# Ограничение частоты запросов мешает адверсариальным прогонам с десятками входов.
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {"login": None, "anon": None}}  # noqa: F405

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "CRITICAL"},
}
