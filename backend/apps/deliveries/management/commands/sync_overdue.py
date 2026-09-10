"""Фиксация просроченных рейсов в истории. Подходит для запуска по cron."""
from django.core.management.base import BaseCommand

from apps.deliveries.services import DeliveryService


class Command(BaseCommand):
    help = "Записывает событие DEADLINE_PASSED для рейсов с истёкшим сроком прибытия."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=1000, help="Максимум рейсов за запуск")

    def handle(self, *args, **options):
        count = DeliveryService().sync_overdue_events(limit=options["limit"])
        self.stdout.write(self.style.SUCCESS(f"Обработано просроченных рейсов: {count}"))
