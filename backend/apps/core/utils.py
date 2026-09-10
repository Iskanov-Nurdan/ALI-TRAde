import ipaddress

from django.utils import timezone


def now() -> "timezone.datetime":
    return timezone.now()


def humanize_minutes(minutes: int | None) -> str:
    """Переводит минуты в читаемый вид: 87 -> '1 ч 27 мин'."""
    if not minutes or minutes <= 0:
        return ""
    hours, mins = divmod(int(minutes), 60)
    if hours and mins:
        return f"{hours} ч {mins} мин"
    if hours:
        return f"{hours} ч"
    return f"{mins} мин"


def client_ip(request) -> str | None:
    """IP клиента. Заголовок прокси принимается, только если это разрешено настройкой.

    Значение всегда валидируется: подделанный заголовок не должен попадать в базу.
    """
    from django.conf import settings

    candidates = []
    if getattr(settings, "TRUST_PROXY_IP_HEADER", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        candidates.extend(part.strip() for part in forwarded.split(",") if part.strip())
    candidates.append((request.META.get("REMOTE_ADDR") or "").strip())

    for candidate in candidates:
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return None
