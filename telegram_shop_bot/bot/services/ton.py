"""Оплата в TON с автоматической проверкой по блокчейну (toncenter API).

Схема: покупатель переводит нужную сумму TON на кошелёк магазина, указав в
комментарии уникальный код заказа (memo). Бот периодически (и по кнопке
«Проверить оплату») запрашивает входящие транзакции кошелька через toncenter,
находит перевод с нужным комментарием и суммой — и автоматически выдаёт товар.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

TON_DECIMALS = 1_000_000_000  # 1 TON = 10^9 nanoton


def ton_nano_for(price_units: int, ton_rate: float) -> int:
    """Сколько нанотон нужно за товар. ton_rate — единиц цены в 1 TON."""
    nano = round(price_units / ton_rate * TON_DECIMALS)
    return max(nano, 1)


def format_ton(nano: int) -> str:
    """Нанотон → строка вида '1.5' (без лишних нулей)."""
    s = f"{nano / TON_DECIMALS:.4f}".rstrip("0").rstrip(".")
    return s or "0"


def match_payment(
    incoming: list[dict], memo: str, required_nano: int, tolerance_nano: int = 0
) -> Optional[dict]:
    """Найти входящий перевод с нужным комментарием и достаточной суммой."""
    memo = (memo or "").strip()
    for tx in incoming:
        if (tx.get("comment") or "").strip() != memo:
            continue
        if int(tx.get("value_nano", 0)) + tolerance_nano >= required_nano:
            return tx
    return None


class TonClient:
    """Тонкий клиент toncenter API v2 (только чтение входящих транзакций)."""

    def __init__(self, api_url: str, api_key: str = "", timeout: int = 20) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    @staticmethod
    def parse(data: dict) -> list[dict]:
        """Из ответа toncenter достать входящие переводы с комментариями."""
        out: list[dict] = []
        for tx in data.get("result", []) or []:
            in_msg = tx.get("in_msg") or {}
            value = in_msg.get("value")
            source = in_msg.get("source") or ""
            if value is None or not source:
                # без внешнего отправителя это не пользовательская оплата
                continue
            comment = in_msg.get("message")
            if comment is None:
                comment = (in_msg.get("msg_data") or {}).get("text") or ""
            out.append({
                "comment": comment or "",
                "value_nano": int(value),
                "hash": (tx.get("transaction_id") or {}).get("hash", ""),
                "utime": tx.get("utime", 0),
                "source": source,
            })
        return out

    async def get_incoming(self, address: str, limit: int = 40) -> list[dict]:
        params = {"address": address, "limit": limit}
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        url = f"{self.api_url}/getTransactions"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("toncenter HTTP %s: %s", resp.status, (await resp.text())[:200])
                        return []
                    data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("toncenter недоступен: %s", exc)
            return []
        return self.parse(data)


async def check_ton_order(bot, config, db, ton_client: TonClient, order: Any) -> bool:
    """Проверить оплату одного заказа сейчас. True — если оплачен и выдан."""
    from .orders import approve_and_deliver

    incoming = await ton_client.get_incoming(config.ton_wallet)
    if match_payment(incoming, order["memo"], order["ton_nano"]) is None:
        return False
    return await approve_and_deliver(bot, config, db, order["id"]) is not None


async def ton_watch_loop(bot, config, db, ton_client: TonClient, interval: int = 25) -> None:
    """Фоновая проверка всех ожидающих TON-заказов."""
    from .orders import approve_and_deliver

    logger.info("TON-watcher запущен (кошелёк %s, курс %s)", config.ton_wallet, config.ton_rate)
    while True:
        try:
            pending = await db.list_pending_ton_orders()
            if pending:
                incoming = await ton_client.get_incoming(config.ton_wallet)
                for order in pending:
                    if match_payment(incoming, order["memo"], order["ton_nano"]):
                        res = await approve_and_deliver(bot, config, db, order["id"])
                        if res:
                            logger.info("TON-заказ #%s подтверждён автоматически", order["id"])
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — фоновый цикл не должен падать
            logger.exception("Ошибка в ton_watch_loop")
        await asyncio.sleep(interval)
