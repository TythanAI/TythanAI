"""Точка входа CS2-снайпера.

Запуск:
    cd cs2_skin_sniper
    pip install -r requirements.txt
    cp .env.example .env      # впиши BOT_TOKEN и ADMIN_IDS
    python run.py
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from bot.config import Config
from bot.database import Database
from bot.handlers import admin
from bot.markets.base import Market
from bot.markets.dmarket import DMarketMarket
from bot.markets.mock import MockMarket
from bot.markets.steam import SteamMarket
from bot.services.monitor import monitor_loop

logger = logging.getLogger("sniper")


def build_markets(config: Config) -> list[Market]:
    markets: list[Market] = []
    for name in config.markets:
        if name == "dmarket":
            if config.dmarket_configured:
                markets.append(DMarketMarket(config.dmarket_public_key,
                                             config.dmarket_secret_key, config.dmarket_api_url))
            else:
                logger.warning("DMarket в списке, но нет ключей — пропускаю (только мониторинг).")
        elif name == "steam":
            markets.append(SteamMarket())
        elif name == "mock":
            markets.append(MockMarket())
    return markets


async def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    config = Config.load()
    db = Database(config.db_path)
    await db.connect(config)

    bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(admin.router)

    markets = build_markets(config)
    await bot.set_my_commands([
        BotCommand(command="start", description="Панель управления"),
        BotCommand(command="help", description="Меню"),
    ])

    me = await bot.get_me()
    logger.info("Снайпер @%s запущен. Площадки: %s. Админы: %s",
                me.username, [m.name for m in markets], config.admin_ids)

    monitor_task = asyncio.create_task(monitor_loop(bot, config, db, markets))
    try:
        await dp.start_polling(bot, config=config, db=db, markets=markets)
    finally:
        monitor_task.cancel()
        for m in markets:
            await m.close()
        await db.close()
        await bot.session.close()
        logger.info("Снайпер остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
