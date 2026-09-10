# -*- coding: utf-8 -*-
"""Атака на производительность списков: N+1 по справочнику курсов валют."""
from django.db import connection
from django.test.utils import CaptureQueriesContext

from .base import AdversarialBase


def rate_queries(context) -> int:
    return sum(1 for query in context.captured_queries if "currency_rates" in query["sql"])


class CurrencyRateNPlusOne(AdversarialBase):
    """Каждая строка списка сама лезет в справочник курсов."""

    def setUp(self):
        super().setUp()
        for index in range(30):
            self.make_delivery(number=f"01KG{index:04d}AB")

    def test_delivery_list_reads_currency_rates_once_per_request(self):
        """DeliveryListSerializer.get_expense_total_converted вызывает
        CurrencyRateService.convert_totals для КАЖДОЙ строки.

        convert_totals -> all_rates() -> ensure_defaults() + выборка курсов,
        то есть два SELECT к currency_rates на каждый рейс. Курсы одинаковы
        для всей выдачи, кэша нет; при page_size=200 это 400 лишних запросов
        на один список.
        """
        self.auth(self.employee)

        with CaptureQueriesContext(connection) as context:
            response = self.client.get("/api/deliveries/?page_size=30")

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            rate_queries(context),
            2,
            f"на 30 строк списка сделано {rate_queries(context)} запросов к currency_rates "
            f"(всего запросов за ответ: {len(context.captured_queries)})",
        )

    def test_vehicle_search_reads_currency_rates_once_per_request(self):
        """Тот же N+1 в поиске по номеру машины.

        VehicleSearchView отдаёт до 100 рейсов тем же сериализатором и без
        пагинации — до 200 запросов к справочнику курсов на один поиск.
        """
        self.auth(self.employee)

        with CaptureQueriesContext(connection) as context:
            response = self.client.get("/api/vehicles/search/?q=01KG")

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            rate_queries(context),
            2,
            f"поиск по номеру сделал {rate_queries(context)} запросов к currency_rates "
            f"(всего запросов за ответ: {len(context.captured_queries)})",
        )
