"""Фоновый монитор: опрашивает площадки, матчит правила, шлёт алерты и (на
поддерживающих площадках) авто-покупает с учётом защиты."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from .. import texts
from ..config import Config
from ..database import Database
from ..markets.base import Market
from ..rules import matching_rules
from ..safety import SafetyLimits, evaluate_buy

logger = logging.getLogger(__name__)


async def notify(bot: Bot, config: Config, text: str) -> None:
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, text, disable_web_page_preview=True)
        except Exception:  # noqa: BLE001
            logger.warning("Не удалось отправить админу %s", admin_id)


async def _attempt_buy(bot: Bot, config: Config, db: Database, market: Market,
                       listing, autobuy: bool, dry_run: bool, limits: SafetyLimits) -> None:
    balance = await market.get_balance()
    spent = await db.spent_today()
    ok, reason = evaluate_buy(
        listing.price, autobuy=autobuy, balance=balance, spent_today=spent, limits=limits
    )
    if not ok:
        await db.add_purchase(listing.market, listing.listing_id, listing.name,
                              listing.price, "skipped", reason)
        await notify(bot, config, texts.skipped_note(listing, reason))
        return
    if dry_run:
        await db.add_purchase(listing.market, listing.listing_id, listing.name,
                              listing.price, "dry_run", "dry-run")
        await notify(bot, config, texts.dry_run_note(listing))
        return
    result = await market.buy(listing)
    status = "bought" if result.ok else "failed"
    await db.add_purchase(listing.market, listing.listing_id, listing.name,
                          listing.price, status, result.message)
    await notify(bot, config,
                 texts.bought_note(listing, result.message) if result.ok
                 else texts.buy_failed_note(listing, result.message))


async def run_once(bot: Bot, config: Config, db: Database, markets: list[Market]) -> None:
    if not await db.get_bool("monitoring"):
        return
    rules = await db.list_rules(only_active=True)
    if not rules:
        return
    autobuy = await db.get_bool("autobuy")
    dry_run = await db.get_bool("dry_run")
    limits = SafetyLimits(
        max_item_price=await db.get_float("max_item_price"),
        daily_limit=await db.get_float("daily_limit"),
        min_balance=await db.get_float("min_balance"),
    )
    for market in markets:
        try:
            listings = await market.fetch_listings(rules)
        except Exception:  # noqa: BLE001
            logger.exception("Ошибка получения лотов с %s", market.name)
            continue
        for listing in listings:
            matched = matching_rules(rules, listing)
            if not matched:
                continue
            if await db.is_seen(listing.market, listing.listing_id):
                continue
            await db.mark_seen(listing.market, listing.listing_id)
            await notify(bot, config, texts.listing_alert(listing))
            rule = matched[0]
            if rule.autobuy and market.supports_autobuy:
                await _attempt_buy(bot, config, db, market, listing, autobuy, dry_run, limits)


async def monitor_loop(bot: Bot, config: Config, db: Database, markets: list[Market]) -> None:
    logger.info("Монитор запущен: %s, интервал %sс",
                [m.name for m in markets], config.poll_interval)
    while True:
        try:
            await run_once(bot, config, db, markets)
            await db.prune_seen(7)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — цикл не должен падать
            logger.exception("Ошибка в monitor_loop")
        await asyncio.sleep(config.poll_interval)
