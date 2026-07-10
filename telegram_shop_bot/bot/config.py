"""Загрузка настроек бота из переменных окружения (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent


def _parse_admin_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if part.lstrip("-").isdigit():
            ids.append(int(part))
    return ids


@dataclass(frozen=True)
class Config:
    """Все настройки бота в одном месте."""

    bot_token: str
    admin_ids: list[int]
    shop_name: str
    currency: str
    provider_token: str
    support_contact: str
    db_path: Path

    @property
    def is_stars(self) -> bool:
        return self.currency.upper() == "XTR"

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids

    @classmethod
    def load(cls) -> "Config":
        load_dotenv(BASE_DIR / ".env")

        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен от @BotFather."
            )

        admin_ids = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
        if not admin_ids:
            raise RuntimeError(
                "ADMIN_IDS не задан. Укажи свой Telegram ID в .env "
                "(узнать можно у бота @userinfobot)."
            )

        currency = (os.getenv("CURRENCY", "XTR").strip() or "XTR").upper()
        provider_token = os.getenv("PROVIDER_TOKEN", "").strip()
        if currency != "XTR" and not provider_token:
            raise RuntimeError(
                f"Для валюты {currency} нужен PROVIDER_TOKEN. "
                "Проще использовать CURRENCY=XTR (Telegram Stars) — тогда провайдер не нужен."
            )

        raw_db = os.getenv("DB_PATH", "").strip() or "data/shop.db"
        db_path = Path(raw_db)
        if not db_path.is_absolute():
            db_path = BASE_DIR / db_path

        return cls(
            bot_token=token,
            admin_ids=admin_ids,
            shop_name=os.getenv("SHOP_NAME", "Магазин").strip() or "Магазин",
            currency=currency,
            provider_token=provider_token,
            support_contact=os.getenv("SUPPORT_CONTACT", "").strip(),
            db_path=db_path,
        )
