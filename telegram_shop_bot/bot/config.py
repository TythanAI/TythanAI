"""Загрузка настроек бота из переменных окружения (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Способы оплаты:
#   stars    — Telegram Stars (звёзды), валюта XTR. Ничего подключать не нужно.
#   provider — Telegram Payments через провайдера (карты, рубли). Нужен PROVIDER_TOKEN.
#   manual   — оплата на карту/крипту вручную, админ подтверждает. Ничего не подключать.
PAYMENT_METHODS = {"stars", "provider", "manual"}

_CURRENCY_SYMBOLS = {
    "XTR": "⭐",
    "RUB": "₽",
    "USD": "$",
    "EUR": "€",
    "UAH": "₴",
    "KZT": "₸",
    "BYN": "Br",
}


def currency_symbol(currency: str) -> str:
    return _CURRENCY_SYMBOLS.get(currency.upper(), currency.upper())


def _parse_admin_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if part.lstrip("-").isdigit():
            ids.append(int(part))
    return ids


def _parse_int(raw: str, default: int = 0) -> int:
    raw = (raw or "").strip()
    return int(raw) if raw.lstrip("-").isdigit() else default


def _parse_float(raw: str, default: float = 0.0) -> float:
    try:
        return float((raw or "").strip().replace(",", "."))
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    """Все настройки бота в одном месте."""

    bot_token: str
    admin_ids: list[int]
    shop_name: str
    payment_method: str
    currency: str
    provider_token: str
    payment_details: str
    support_contact: str
    db_path: Path
    # TON (крипто-оплата, опционально)
    ton_wallet: str
    ton_rate: float          # сколько единиц цены (напр. рублей) в 1 TON
    ton_api_url: str
    ton_api_key: str
    # Бэкапы в Telegram-чат (опционально)
    backup_chat_id: int | None
    backup_interval_hours: int

    @property
    def is_stars(self) -> bool:
        return self.payment_method == "stars"

    @property
    def is_manual(self) -> bool:
        return self.payment_method == "manual"

    @property
    def is_provider(self) -> bool:
        return self.payment_method == "provider"

    @property
    def ton_enabled(self) -> bool:
        return bool(self.ton_wallet) and self.ton_rate > 0

    @property
    def backup_enabled(self) -> bool:
        return self.backup_chat_id is not None and self.backup_interval_hours > 0

    @property
    def enabled_methods(self) -> list[str]:
        """Способы оплаты, доступные покупателю (основной + TON, если включён)."""
        methods = [self.payment_method]
        if self.ton_enabled:
            methods.append("ton")
        return methods

    @property
    def symbol(self) -> str:
        return currency_symbol(self.currency)

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

        method = (os.getenv("PAYMENT_METHOD", "stars").strip() or "stars").lower()
        if method not in PAYMENT_METHODS:
            raise RuntimeError(
                f"PAYMENT_METHOD='{method}' неизвестен. Допустимо: "
                "stars (звёзды), provider (карты через провайдера), manual (карта/крипта вручную)."
            )

        provider_token = os.getenv("PROVIDER_TOKEN", "").strip()
        payment_details = os.getenv("PAYMENT_DETAILS", "").strip()

        if method == "stars":
            currency = "XTR"
        else:
            currency = (os.getenv("CURRENCY", "RUB").strip() or "RUB").upper()
            if currency == "XTR":
                # XTR имеет смысл только со способом stars.
                currency = "RUB"

        if method == "provider" and not provider_token:
            raise RuntimeError(
                "PAYMENT_METHOD=provider требует PROVIDER_TOKEN. "
                "Получи его в @BotFather (Bot Settings → Payments) или используй "
                "PAYMENT_METHOD=manual (оплата на карту вручную) / stars (звёзды)."
            )
        if method == "manual" and not payment_details:
            raise RuntimeError(
                "PAYMENT_METHOD=manual требует PAYMENT_DETAILS — реквизиты для оплаты "
                "(например: 'Сбербанк 2202 2000 0000 0000, получатель Иван И.'). "
                "Впиши их в .env."
            )

        raw_db = os.getenv("DB_PATH", "").strip() or "data/shop.db"
        db_path = Path(raw_db)
        if not db_path.is_absolute():
            db_path = BASE_DIR / db_path

        ton_wallet = os.getenv("TON_WALLET", "").strip()
        ton_rate = _parse_float(os.getenv("TON_RATE", ""))
        if ton_wallet and ton_rate <= 0:
            raise RuntimeError(
                "TON_WALLET задан, но TON_RATE не указан. Впиши TON_RATE — сколько "
                "единиц твоей цены равно 1 TON (например, 1 TON = 500 ₽ → TON_RATE=500)."
            )

        backup_chat_raw = os.getenv("BACKUP_CHAT_ID", "").strip()
        backup_chat_id = int(backup_chat_raw) if backup_chat_raw.lstrip("-").isdigit() else None

        return cls(
            bot_token=token,
            admin_ids=admin_ids,
            shop_name=os.getenv("SHOP_NAME", "Магазин").strip() or "Магазин",
            payment_method=method,
            currency=currency,
            provider_token=provider_token,
            payment_details=payment_details,
            support_contact=os.getenv("SUPPORT_CONTACT", "").strip(),
            db_path=db_path,
            ton_wallet=ton_wallet,
            ton_rate=ton_rate,
            ton_api_url=os.getenv("TON_API_URL", "https://toncenter.com/api/v2").strip().rstrip("/")
            or "https://toncenter.com/api/v2",
            ton_api_key=os.getenv("TON_API_KEY", "").strip(),
            backup_chat_id=backup_chat_id,
            backup_interval_hours=_parse_int(os.getenv("BACKUP_INTERVAL_HOURS", "0")),
        )
