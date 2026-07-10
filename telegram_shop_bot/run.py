"""Точка входа бота-магазина.

Запуск:
    cd telegram_shop_bot
    pip install -r requirements.txt
    cp .env.example .env      # затем впиши BOT_TOKEN и ADMIN_IDS
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
from bot.handlers import admin, payments, user

logger = logging.getLogger("bot")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    config = Config.load()
    db = Database(config.db_path, currency=config.currency)
    await db.connect()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    # Порядок важен: админка (с фильтром IsAdmin) → оплата → пользователь (fallback).
    dp.include_router(admin.router)
    dp.include_router(payments.router)
    dp.include_router(user.router)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Открыть магазин"),
            BotCommand(command="help", description="Меню"),
        ]
    )

    me = await bot.get_me()
    logger.info("Бот @%s запущен. Валюта: %s. Админы: %s", me.username, config.currency, config.admin_ids)

    try:
        await dp.start_polling(bot, db=db, config=config)
    finally:
        await db.close()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
