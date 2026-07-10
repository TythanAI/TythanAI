"""DMarket — мониторинг + автопокупка по официальному Trading API.

Чтение (market/items) публичное; баланс и покупка подписываются ключом
(Ed25519). Подпись: X-Request-Sign = "dmar ed25519 " + hex(sign(method+path+body+ts)).

⚠️ Покупка тратит РЕАЛЬНЫЕ деньги. Точная схема эндпоинта покупки и подписи может
меняться — сверь с актуальной докой DMarket (docs.dmarket.com) и сначала проверь
всё в DRY_RUN. Логика поиска/защиты полностью покрыта тестами на mock-маркете.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import aiohttp

from ..models import Listing, Rule
from .base import BuyResult, Market

logger = logging.getLogger(__name__)

_GAME_ID = "a8db"  # CS2 / CS:GO на DMarket


def _price_to_usd(value) -> float:
    """DMarket отдаёт цены в центах (строкой или числом)."""
    try:
        return int(value) / 100
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0


class DMarketMarket(Market):
    name = "dmarket"
    supports_autobuy = True

    def __init__(self, public_key: str, secret_key: str,
                 api_url: str = "https://api.dmarket.com", timeout: int = 20) -> None:
        self.public_key = public_key
        self.secret_key = secret_key
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    # ── подпись запроса ───────────────────────────────────────────────
    def _headers(self, method: str, path: str, body: str = "") -> dict:
        from nacl.signing import SigningKey  # ленивый импорт: нужен только для авторизации

        ts = str(int(time.time()))
        to_sign = method.upper() + path + body + ts
        seed = bytes.fromhex(self.secret_key)[:32]
        signature = SigningKey(seed).sign(to_sign.encode()).signature.hex()
        return {
            "X-Api-Key": self.public_key,
            "X-Request-Sign": "dmar ed25519 " + signature,
            "X-Sign-Date": ts,
            "Content-Type": "application/json",
        }

    # ── чтение рынка ──────────────────────────────────────────────────
    @staticmethod
    def parse_items(data: dict) -> list[Listing]:
        out: list[Listing] = []
        for obj in data.get("objects", []) or []:
            price = _price_to_usd((obj.get("price") or {}).get("USD"))
            if price <= 0:
                continue
            extra = obj.get("extra") or {}
            float_value = extra.get("floatValue")
            paint_seed = extra.get("paintSeed")
            stickers = [s.get("name", "") for s in (extra.get("stickers") or []) if s.get("name")]
            offer_id = obj.get("itemId") or obj.get("offerId") or extra.get("offerId") or ""
            out.append(Listing(
                market="dmarket",
                listing_id=str(offer_id),
                name=obj.get("title") or "",
                price=price,
                float_value=float(float_value) if float_value is not None else None,
                paint_seed=int(paint_seed) if paint_seed is not None else None,
                stickers=stickers,
                url=f"https://dmarket.com/ingame-items/item-list/csgo-skins?title={obj.get('title','')}",
                ref_price=_price_to_usd((obj.get("suggestedPrice") or {}).get("USD"))
                or _price_to_usd((obj.get("recommendedPrice") or {}).get("USD")) or None,
                extra={"offerId": str(offer_id)},
            ))
        return out

    async def fetch_listings(self, rules: list[Rule]) -> list[Listing]:
        queries = {r.name_query.strip() for r in rules if r.name_query.strip()}
        if not queries:
            return []
        session = await self._get_session()
        results: list[Listing] = []
        for q in queries:
            path = (f"/exchange/v1/market/items?gameId={_GAME_ID}&currency=USD&limit=100"
                    f"&orderBy=price&orderDir=asc&title={aiohttp.helpers.quote(q, safe='')}")
            try:
                async with session.get(self.api_url + path) as resp:
                    if resp.status != 200:
                        logger.warning("DMarket HTTP %s для '%s'", resp.status, q)
                        continue
                    data = await resp.json()
                results.extend(self.parse_items(data))
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning("DMarket недоступен: %s", exc)
            await asyncio.sleep(0.3)
        return results

    async def get_balance(self) -> float | None:
        if not (self.public_key and self.secret_key):
            return None
        session = await self._get_session()
        path = "/account/v1/balance"
        try:
            async with session.get(self.api_url + path, headers=self._headers("GET", path)) as resp:
                if resp.status != 200:
                    logger.warning("DMarket balance HTTP %s", resp.status)
                    return None
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("DMarket balance недоступен: %s", exc)
            return None
        return _price_to_usd(data.get("usd") or data.get("usdAvailableToWithdraw"))

    async def buy(self, listing: Listing) -> BuyResult:
        if not (self.public_key and self.secret_key):
            return BuyResult(False, "Нет ключей DMarket")
        offer_id = listing.extra.get("offerId") or listing.listing_id
        body_obj = {"offers": [{
            "offerId": offer_id,
            "price": {"amount": str(int(round(listing.price * 100))), "currency": "USD"},
        }]}
        body = json.dumps(body_obj)
        path = "/exchange/v1/offers-buy"
        session = await self._get_session()
        try:
            async with session.post(self.api_url + path, data=body,
                                    headers=self._headers("POST", path, body)) as resp:
                text = await resp.text()
                if resp.status not in (200, 201):
                    return BuyResult(False, f"DMarket HTTP {resp.status}: {text[:150]}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            return BuyResult(False, f"Сеть: {exc}")
        return BuyResult(True, "Куплено на DMarket", order_id=str(offer_id))

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
