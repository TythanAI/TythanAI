"""Оплата: выставление счёта, предчек и выдача товара после оплаты.

По умолчанию используется Telegram Stars (валюта XTR) — внешний платёжный
провайдер не нужен. Для обычных валют укажи PROVIDER_TOKEN в .env.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from .. import texts
from ..config import Config
from ..database import Database
from ..keyboards import ProductCB

logger = logging.getLogger(__name__)
router = Router(name="payments")

_PAYLOAD_PREFIX = "buy:"


def _invoice_amount(price: int, config: Config) -> int:
    # Для Stars (XTR) сумма указывается в звёздах как есть.
    # Для обычных валют — в минимальных единицах (копейки/центы).
    return price if config.is_stars else price * 100


def _parse_payload(payload: str) -> int | None:
    if not payload.startswith(_PAYLOAD_PREFIX):
        return None
    raw = payload[len(_PAYLOAD_PREFIX):]
    return int(raw) if raw.isdigit() else None


@router.callback_query(ProductCB.filter(F.action == "buy"))
async def cb_buy(
    query: CallbackQuery, callback_data: ProductCB, db: Database, config: Config
) -> None:
    if query.from_user is None or query.message is None:
        return
    product = await db.get_product(callback_data.product_id)
    if product is None or not product["is_active"]:
        await query.answer("Товар недоступен", show_alert=True)
        return
    if await db.available_count(product["id"]) <= 0:
        await query.answer("Нет в наличии", show_alert=True)
        return

    title = product["title"][:32]
    description = (product["description"] or product["title"])[:255]
    await query.message.answer_invoice(
        title=title,
        description=description,
        payload=f"{_PAYLOAD_PREFIX}{product['id']}",
        currency=config.currency,
        prices=[LabeledPrice(label=title, amount=_invoice_amount(product["price"], config))],
        provider_token=config.provider_token,
    )
    await query.answer()


@router.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery, db: Database) -> None:
    product_id = _parse_payload(pcq.invoice_payload)
    product = await db.get_product(product_id) if product_id is not None else None
    if product is None or not product["is_active"] or await db.available_count(product["id"]) <= 0:
        await pcq.answer(ok=False, error_message="Извините, товар только что закончился.")
        return
    await pcq.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, bot, db: Database, config: Config) -> None:
    sp = message.successful_payment
    user = message.from_user
    if sp is None or user is None:
        return

    charge_id = sp.telegram_payment_charge_id
    product_id = _parse_payload(sp.invoice_payload)
    product = await db.get_product(product_id) if product_id is not None else None

    delivered = None
    if product is not None:
        delivered = await db.deliver_one(product, user.id, charge_id)

    # Наличие закончилось между оплатой и выдачей — возвращаем звёзды.
    if delivered is None:
        if config.is_stars:
            try:
                await bot.refund_star_payment(
                    user_id=user.id, telegram_payment_charge_id=charge_id
                )
            except Exception:  # noqa: BLE001 — возврат best-effort, логируем и идём дальше
                logger.exception("Не удалось вернуть оплату пользователю %s", user.id)
        await message.answer(texts.refunded_sold_out())
        for admin_id in config.admin_ids:
            try:
                await bot.send_message(
                    admin_id,
                    f"⚠️ Оплата без выдачи (наличие кончилось). "
                    f"Покупатель id{user.id}, charge {charge_id}.",
                )
            except Exception:  # noqa: BLE001
                logger.warning("Не удалось уведомить админа %s", admin_id)
        return

    await message.answer(texts.delivery(product["title"], delivered["payload"]))

    for admin_id in config.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                texts.new_sale_admin(
                    product["title"], user.id, user.username, product["price"], config.currency
                ),
            )
        except Exception:  # noqa: BLE001
            logger.warning("Не удалось уведомить админа %s о продаже", admin_id)
