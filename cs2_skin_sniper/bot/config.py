"""Настройки из переменных окружения (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent


def _admins(raw: str) -> list[int]:
    out = []
    for p in raw.replace(";", ",").split(","):
        p = p.strip()
        if p.lstrip("-").isdigit():
            out.append(int(p))
    return out


def _int(raw: str, default: int) -> int:
    raw = (raw or "").strip()
    return int(raw) if raw.lstrip("-").isdigit() else default


def _float(raw: str, default: float) -> float:
    try:
        return float((raw or "").strip().replace(",", "."))
    except ValueError:
        return default


def _bool(raw: str, default: bool) -> bool:
    raw = (raw or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: list[int]
    poll_interval: int
    markets: list[str]                 # среди: dmarket, steam, mock
    dmarket_public_key: str
    dmarket_secret_key: str
    dmarket_api_url: str
    # Значения-ПО-УМОЛЧАНИЮ для защиты (дальше живут в Б.Д. и меняются из бота)
    default_autobuy: bool
    default_dry_run: bool
    default_max_item_price: float
    default_daily_limit: float
    default_min_balance: float
    db_path: Path

    @property
    def dmarket_configured(self) -> bool:
        return bool(self.dmarket_public_key and self.dmarket_secret_key)

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids

    @classmethod
    def load(cls) -> "Config":
        load_dotenv(BASE_DIR / ".env")

        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен.")
        admins = _admins(os.getenv("ADMIN_IDS", ""))
        if not admins:
            raise RuntimeError("ADMIN_IDS не задан (узнать свой ID: @userinfobot).")

        dm_pub = os.getenv("DMARKET_PUBLIC_KEY", "").strip()
        dm_sec = os.getenv("DMARKET_SECRET_KEY", "").strip()

        raw_markets = os.getenv("MARKETS", "").strip()
        if raw_markets:
            markets = [m.strip().lower() for m in raw_markets.split(",") if m.strip()]
        else:
            # по умолчанию: Steam (мониторинг, без ключей) + DMarket, если есть ключи
            markets = ["steam"] + (["dmarket"] if (dm_pub and dm_sec) else [])
        markets = [m for m in markets if m in ("dmarket", "steam", "mock")] or ["steam"]

        raw_db = os.getenv("DB_PATH", "").strip() or "data/sniper.db"
        db_path = Path(raw_db)
        if not db_path.is_absolute():
            db_path = BASE_DIR / db_path

        return cls(
            bot_token=token,
            admin_ids=admins,
            poll_interval=max(5, _int(os.getenv("POLL_INTERVAL"), 30)),
            markets=markets,
            dmarket_public_key=dm_pub,
            dmarket_secret_key=dm_sec,
            dmarket_api_url=os.getenv("DMARKET_API_URL", "https://api.dmarket.com").strip().rstrip("/")
            or "https://api.dmarket.com",
            default_autobuy=_bool(os.getenv("AUTOBUY"), False),
            default_dry_run=_bool(os.getenv("DRY_RUN"), True),
            default_max_item_price=_float(os.getenv("MAX_ITEM_PRICE"), 50.0),
            default_daily_limit=_float(os.getenv("DAILY_LIMIT"), 100.0),
            default_min_balance=_float(os.getenv("MIN_BALANCE"), 0.0),
            db_path=db_path,
        )
