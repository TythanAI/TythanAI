"""Единый интерфейс площадки. Новый маркет = новый подкласс Market."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Listing, Rule


@dataclass
class BuyResult:
    ok: bool
    message: str = ""
    order_id: str | None = None


class Market:
    """Базовый адаптер. Методы переопределяются в конкретных площадках."""

    name: str = "base"
    supports_autobuy: bool = False

    async def fetch_listings(self, rules: list[Rule]) -> list[Listing]:
        """Свежие лоты-кандидаты (обычно ищем по названиям из правил)."""
        return []

    async def get_balance(self) -> float | None:
        """Баланс аккаунта в USD (None — если площадка не даёт/не нужно)."""
        return None

    async def buy(self, listing: Listing) -> BuyResult:
        """Купить лот. По умолчанию не поддерживается."""
        return BuyResult(False, "Покупка на этой площадке не поддерживается")

    async def close(self) -> None:
        """Освободить ресурсы (сессии) при остановке."""
        return None
