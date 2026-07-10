"""Защита автопокупки: лимиты и проверки перед тратой денег."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SafetyLimits:
    max_item_price: float   # максимум за один предмет, USD
    daily_limit: float      # дневной лимит трат, USD
    min_balance: float      # не опускать баланс ниже, USD


def evaluate_buy(
    price: float, *, autobuy: bool, balance: float | None, spent_today: float,
    limits: SafetyLimits,
) -> tuple[bool, str]:
    """Можно ли покупать. Возвращает (можно, причина_если_нет)."""
    if not autobuy:
        return False, "автопокупка выключена"
    if price <= 0:
        return False, "нет цены"
    if price > limits.max_item_price:
        return False, f"дороже лимита за предмет ({limits.max_item_price:g}$)"
    if spent_today + price > limits.daily_limit:
        return False, f"превышен дневной лимит ({limits.daily_limit:g}$)"
    if balance is None:
        return False, "баланс неизвестен — не рискуем"
    if balance - price < limits.min_balance:
        return False, f"сработала защита баланса (мин. {limits.min_balance:g}$)"
    return True, "ok"
