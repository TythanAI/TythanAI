"""Steam Community Market — ТОЛЬКО мониторинг/алерты.

У Steam нет официального API покупки, а автоматизация сайта нарушает правила
Steam и ведёт к бану — поэтому здесь supports_autobuy = False. Отдаём цены по
названию (float/paint seed Steam не публикует).
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

import aiohttp

from ..models import Listing, Rule
from .base import Market

logger = logging.getLogger(__name__)

_SEARCH = "https://steamcommunity.com/market/search/render/"
_APPID = 730  # CS2 / CS:GO


class SteamMarket(Market):
    name = "steam"
    supports_autobuy = False

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "cs2-sniper/1.0"},
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )
        return self._session

    @staticmethod
    def parse_search(data: dict) -> list[Listing]:
        out: list[Listing] = []
        for r in data.get("results", []) or []:
            hash_name = r.get("hash_name") or r.get("name") or ""
            price_cents = r.get("sell_price")
            if not hash_name or price_cents is None:
                continue
            price = int(price_cents) / 100
            url = f"https://steamcommunity.com/market/listings/{_APPID}/{quote(hash_name)}"
            out.append(Listing(
                market="steam",
                listing_id=f"{hash_name}@{price_cents}",   # новая цена → новый алерт
                name=r.get("name") or hash_name,
                price=price,
                url=url,
                extra={"sell_listings": r.get("sell_listings")},
            ))
        return out

    async def fetch_listings(self, rules: list[Rule]) -> list[Listing]:
        queries = {r.name_query.strip() for r in rules if r.name_query.strip()}
        if not queries:
            return []
        session = await self._get_session()
        results: list[Listing] = []
        for q in queries:
            params = {"appid": _APPID, "norender": 1, "count": 20,
                      "query": q, "sort_column": "price", "sort_dir": "asc"}
            try:
                async with session.get(_SEARCH, params=params) as resp:
                    if resp.status != 200:
                        logger.warning("Steam HTTP %s для '%s'", resp.status, q)
                        continue
                    data = await resp.json()
                results.extend(self.parse_search(data))
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning("Steam недоступен: %s", exc)
            await asyncio.sleep(1.0)  # бережём лимиты Steam
        return results

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
