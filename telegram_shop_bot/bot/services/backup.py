"""Резервные копии базы данных в Telegram-чат.

Бот периодически (и по кнопке в админке) отправляет консистентный снимок
SQLite-базы в указанный чат/канал (BACKUP_CHAT_ID). Снимок делается через
`VACUUM INTO`, поэтому он целостный даже во время работы бота.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from ..config import Config
from ..database import Database

logger = logging.getLogger(__name__)


async def make_snapshot(db: Database) -> Path:
    """Целостная копия базы во временный файл. Возвращает путь к копии."""
    dest = db.path.parent / f".backup_{int(time.time())}.db"
    if dest.exists():
        dest.unlink()
    await db.conn.commit()  # чтобы снимок не ждал открытую транзакцию
    await db.conn.execute("VACUUM INTO ?", (str(dest),))
    return dest


async def send_backup(bot: Bot, config: Config, db: Database, chat_id: int | None = None) -> bool:
    """Сделать снимок и отправить документом. Временный файл удаляется."""
    chat = chat_id if chat_id is not None else config.backup_chat_id
    if chat is None:
        return False
    dest = await make_snapshot(db)
    try:
        caption = f"🗄 Бэкап базы · {datetime.now():%Y-%m-%d %H:%M}"
        await bot.send_document(chat, FSInputFile(dest, filename="shop.db"), caption=caption)
        return True
    finally:
        try:
            dest.unlink()
        except OSError:
            pass


async def backup_loop(bot: Bot, config: Config, db: Database) -> None:
    """Фоновая отправка бэкапов каждые BACKUP_INTERVAL_HOURS часов."""
    interval = max(1, config.backup_interval_hours) * 3600
    logger.info("Бэкапы включены: каждые %s ч в чат %s", config.backup_interval_hours, config.backup_chat_id)
    while True:
        await asyncio.sleep(interval)
        try:
            await send_backup(bot, config, db)
            logger.info("Бэкап отправлен")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — фоновый цикл не должен падать
            logger.exception("Не удалось отправить бэкап")
