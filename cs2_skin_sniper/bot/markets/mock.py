"""Тестовый маркет-симулятор: без сети и без денег.

Позволяет прогнать всю логику (поиск редких лотов, алерты, защита, покупка)
локально. Управляется прямо из кода/тестов: задаёшь listings и balance.
Включается через MARKETS=mock.
"""

from __future__ import annotations

from ..models import Listing, Rule
from .base import BuyResult, Market


class MockMarket(Market):
    name = "mock"
    supports_autobuy = True

    def __init__(self, listings: list[Listing] | None = None, balance: float = 1000.0) -> None:
        self.listings: list[Listing] = list(listings or [])
        self.balance = balance
        self.bought: list[Listing] = []

    async def fetch_listings(self, rules: list[Rule]) -> list[Listing]:
        # Возвращаем все текущие лоты; точную фильтрацию делает движок правил.
        return list(self.listings)

    async def get_balance(self) -> float | None:
        return self.balance

    async def buy(self, listing: Listing) -> BuyResult:
        found = next((x for x in self.listings if x.listing_id == listing.listing_id), None)
        if found is None:
            return BuyResult(False, "Лот уже недоступен")
        if listing.price > self.balance:
            return BuyResult(False, "Недостаточно баланса")
        self.balance -= listing.price
        self.listings.remove(found)
        self.bought.append(found)
        return BuyResult(True, "Куплено (mock)", order_id=f"mock-{listing.listing_id}")
