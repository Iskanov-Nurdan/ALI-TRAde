"""Базовые типы расходов из технического задания."""
from django.db import migrations

INITIAL_TYPES = [
    ("tax", "Налог", 10),
    ("border-payment", "Платёж на границе", 20),
    ("customs", "Таможенный сбор", 30),
    ("axle-fine", "Осевой / штраф за перегруз", 40),
    ("toll-road", "Платная дорога", 50),
    ("loading", "Погрузка", 60),
    ("unloading", "Разгрузка", 70),
    ("repair", "Ремонт", 80),
    ("other", "Другой расход", 999),
]


def create_types(apps, schema_editor):
    ExpenseType = apps.get_model("expenses", "ExpenseType")
    for code, name, order in INITIAL_TYPES:
        ExpenseType.objects.get_or_create(
            code=code, defaults={"name": name, "sort_order": order, "is_active": True}
        )


def remove_types(apps, schema_editor):
    ExpenseType = apps.get_model("expenses", "ExpenseType")
    ExpenseType.objects.filter(code__in=[code for code, _, _ in INITIAL_TYPES]).delete()


class Migration(migrations.Migration):
    dependencies = [("expenses", "0001_initial")]

    operations = [migrations.RunPython(create_types, remove_types)]
