"""Начальное наполнение: администратор, сотрудники и точки.

Запуск: python manage.py seed_demo [--with-deliveries]
Пароли берутся из переменных окружения ADMIN_PASSWORD / DEMO_PASSWORD.
"""
import os
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.deliveries.models import Delivery, DeliveryEvent, DeliveryStatus
from apps.expenses.models import Currency, Expense, ExpenseType, Payer
from apps.points.models import Point

POINTS = [
    ("Бишкек", "г. Бишкек, склад №1", "+996 555 000 001"),
    ("Ош", "г. Ош, терминал", "+996 555 000 002"),
    ("Достук", "КПП Достук", "+996 555 000 003"),
    ("Иркештам", "Граница Иркештам", "+996 555 000 004"),
    ("Склад Кара-Балта", "г. Кара-Балта, промзона", "+996 555 000 005"),
]

EMPLOYEES = [
    ("Сотрудник №3", "employee3"),
    ("Сотрудник №5", "employee5"),
    ("Сотрудник №7", "employee7"),
]


class Command(BaseCommand):
    help = "Создаёт администратора, сотрудников и точки; при флаге — демонстрационные рейсы."

    def add_arguments(self, parser):
        parser.add_argument("--with-deliveries", action="store_true", help="Создать примеры рейсов")

    @transaction.atomic
    def handle(self, *args, **options):
        admin_password = os.getenv("ADMIN_PASSWORD", "admin12345")
        demo_password = os.getenv("DEMO_PASSWORD", "employee12345")

        admin, created = User.objects.get_or_create(
            login="admin",
            defaults={"full_name": "Главный администратор", "role": UserRole.ADMIN, "is_staff": True,
                      "is_superuser": True},
        )
        if created:
            admin.set_password(admin_password)
            admin.save()
            self.stdout.write(self.style.SUCCESS(f"Создан администратор admin / {admin_password}"))
        else:
            self.stdout.write("Администратор уже существует.")

        employees = []
        for full_name, login in EMPLOYEES:
            user, was_created = User.objects.get_or_create(
                login=login, defaults={"full_name": full_name, "role": UserRole.EMPLOYEE}
            )
            if was_created:
                user.set_password(demo_password)
                user.save()
            employees.append(user)
        self.stdout.write(self.style.SUCCESS(f"Сотрудников: {len(employees)} (пароль {demo_password})"))

        points = []
        for name, address, phone in POINTS:
            point, _ = Point.objects.get_or_create(name=name, defaults={"address": address, "phone": phone})
            points.append(point)
        self.stdout.write(self.style.SUCCESS(f"Точек: {len(points)}"))

        if not options["with_deliveries"]:
            return

        if Delivery.objects.exists():
            self.stdout.write("Рейсы уже есть — демонстрационные данные не создаются.")
            return

        now = timezone.now()
        bishkek, osh, dostuk = points[0], points[1], points[2]
        tax_type = ExpenseType.objects.get(code="tax")
        axle_type = ExpenseType.objects.get(code="axle-fine")

        # Прибывший с опозданием рейс
        arrived = Delivery.objects.create(
            point_from=bishkek, point_to=dostuk, vehicle_number="1234 ABC",
            created_by=employees[0], dispatched_by=employees[0], received_by=employees[2],
            dispatched_at=now - timedelta(days=3, hours=4), deadline_at=now - timedelta(days=3),
            received_at=now - timedelta(days=2, hours=23, minutes=33),
            planned_duration_minutes=240, status=DeliveryStatus.ARRIVED,
            deadline_passed_logged=True,
        )
        DeliveryEvent.objects.create(delivery=arrived, event_type=DeliveryEvent.EventType.CREATED,
                                     user=employees[0], event_time=arrived.dispatched_at)
        DeliveryEvent.objects.create(delivery=arrived, event_type=DeliveryEvent.EventType.DISPATCHED,
                                     user=employees[0], event_time=arrived.dispatched_at)
        DeliveryEvent.objects.create(delivery=arrived, event_type=DeliveryEvent.EventType.DEADLINE_PASSED,
                                     event_time=arrived.deadline_at,
                                     comment="Срок прибытия истёк, прибытие не подтверждено.")
        DeliveryEvent.objects.create(delivery=arrived, event_type=DeliveryEvent.EventType.RECEIVED,
                                     user=employees[2], event_time=arrived.received_at,
                                     metadata={"late_minutes": 33})
        Expense.objects.create(delivery=arrived, expense_type=axle_type, amount=100, currency=Currency.USD,
                               payer=Payer.CHINA, description="Осевой — превышение нагрузки",
                               created_by=employees[1])
        Expense.objects.create(delivery=arrived, expense_type=tax_type, amount=30, currency=Currency.USD,
                               payer=Payer.COMPANY, description="Дополнительный налог", created_by=employees[0])

        # Просроченный рейс в пути
        overdue = Delivery.objects.create(
            point_from=bishkek, point_to=dostuk, vehicle_number="01 KG 1234 AB",
            created_by=employees[1], dispatched_by=employees[1],
            dispatched_at=now - timedelta(hours=6), deadline_at=now - timedelta(hours=2),
            planned_duration_minutes=240, status=DeliveryStatus.IN_TRANSIT,
        )
        DeliveryEvent.objects.create(delivery=overdue, event_type=DeliveryEvent.EventType.DISPATCHED,
                                     user=employees[1], event_time=overdue.dispatched_at)
        Expense.objects.create(delivery=overdue, expense_type=tax_type, amount=30, currency=Currency.USD,
                               payer=Payer.COMPANY, description="Платёж на границе", created_by=employees[2])

        # Рейс в пути без просрочки
        in_transit = Delivery.objects.create(
            point_from=osh, point_to=bishkek, vehicle_number="7788 KGZ",
            created_by=employees[2], dispatched_by=employees[2],
            dispatched_at=now - timedelta(hours=1), deadline_at=now + timedelta(hours=5),
            planned_duration_minutes=360, status=DeliveryStatus.IN_TRANSIT,
        )
        DeliveryEvent.objects.create(delivery=in_transit, event_type=DeliveryEvent.EventType.DISPATCHED,
                                     user=employees[2], event_time=in_transit.dispatched_at)

        self.stdout.write(self.style.SUCCESS("Демонстрационные рейсы созданы."))
