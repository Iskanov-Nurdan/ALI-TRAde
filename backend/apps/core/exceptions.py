"""Единый формат ошибок API — внутренние детали наружу не выходят."""
import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


class BusinessError(APIException):
    """Нарушение бизнес-правила (слой services)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Операция недопустима."
    default_code = "business_error"


class NotFoundError(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Объект не найден."
    default_code = "not_found"


class PermissionDeniedError(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Недостаточно прав для выполнения операции."
    default_code = "permission_denied"


def api_exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        exc = BusinessError(detail=list(exc.messages))

    response = exception_handler(exc, context)

    if response is None:
        if isinstance(exc, IntegrityError):
            logger.warning("Конфликт целостности данных: %s", exc)
            return Response(
                {"detail": "Конфликт данных. Проверьте корректность значений.", "code": "integrity_error"},
                status=status.HTTP_409_CONFLICT,
            )
        logger.exception("Необработанная ошибка сервера", exc_info=exc)
        return Response(
            {"detail": "Внутренняя ошибка сервера.", "code": "server_error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    detail = response.data
    if isinstance(detail, dict) and "detail" in detail:
        response.data = {"detail": detail["detail"], "code": getattr(exc, "default_code", "error")}
    else:
        response.data = {
            "detail": "Ошибка валидации данных.",
            "code": "validation_error",
            "errors": detail,
        }
    return response
