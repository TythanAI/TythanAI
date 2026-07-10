"""Модели данных: лот на маркете (Listing) и правило поиска (Rule)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Listing:
    """Один лот на площадке (уже в едином формате, независимо от маркета)."""

    market: str
    listing_id: str          # id лота на площадке (для покупки и защиты от дублей)
    name: str                # напр. "AK-47 | Case Hardened (Field-Tested)"
    price: float             # цена продавца, USD
    float_value: float | None = None
    paint_seed: int | None = None
    stickers: list[str] = field(default_factory=list)
    url: str = ""
    ref_price: float | None = None   # референсная цена (для скидки/«дёшево»)
    extra: dict = field(default_factory=dict)

    def discount(self) -> float | None:
        """Скидка к референсной цене, 0..1 (None, если реф-цены нет)."""
        if not self.ref_price or self.ref_price <= 0:
            return None
        return max(0.0, 1 - self.price / self.ref_price)


@dataclass
class Rule:
    """Правило поиска: какие лоты ловим (и покупать ли автоматически)."""

    id: int
    name_query: str          # подстрока в названии, напр. "Case Hardened"
    max_price: float         # рассматриваем только лоты не дороже
    min_float: float | None  # диапазон float (износ), напр. 0.00–0.07 = Factory New
    max_float: float | None
    seeds: list[int]         # редкие paint seed (пусто = любой)
    stickers: list[str]      # ключевые слова наклеек, любое совпадение (пусто = любые)
    min_discount: float      # требовать цену ниже реф на долю 0..1 (0 = не требовать)
    autobuy: bool            # покупать при совпадении (с учётом глобальной защиты)
    active: bool
