"""Оплата: три способа — Telegram Stars, провайдер (карты), ручное подтверждение.

Мгновенная выдача (stars/provider) — сразу после успешной оплаты.
Ручная оплата (manual) — покупатель платит по реквизитам, админ подтверждает,
затем бот выдаёт товар автоматически.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from .. import keyboards as kb
from .. import texts
from ..config import Config
from ..database import Database
from ..keyboards import PayCB, ProductCB
from ..utils import active_promo, apply_discount

logger = logging.getLogger(__name__)
router = Router(name="payments")

_PREFIX = "buy:"


def _invoice_amount(price: int, config: Config) -> int:
    # Stars (XTR): сумма в звёздах как есть. Обычная валюта: в минимальных единицах.
    return price if config.is_stars else price * 100


def _encode(product_id: int, promo_code: str | None) -> str:
    return f"{_PREFIX}{product_id}:{promo_code or ''}"


def _decode(payload: str) -> tuple[int | None, str | None]:
    if not payload.startswith(_PREFIX):
        return None, None
    rest = payload[len(_PREFIX):]
    pid, _, promo = rest.partition(":")
    return (int(pid) if pid.isdigit() else None), (promo or None)


async def _notify_admins(bot: Bot, config: Config, text: str, markup=None) -> None:
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=markup)
        except Exception:  # noqa: BLE001
            logger.warning("Не удалось уведомить админа %s", admin_id)


@router.callback_query(ProductCB.filter(F.action == "buy"))
async def cb_buy(query: CallbackQuery, callback_data: ProductCB, db: Database,
                 config: Config, state: FSMContext) -> None:
    if query.from_user is None or query.message is None:
        return
    product = await db.get_product(callback_data.product_id)
    if product is None or not product["is_active"]:
        await query.answer("Товар недоступен", show_alert=True)
        return
    if await db.available_count(product["id"]) <= 0:
        await query.answer("Нет в наличии", show_alert=True)
        return

    promo = await active_promo(state, db)
    promo_code = promo["code"] if promo else None
    price = apply_discount(product["price"], promo)

    if config.is_manual:
        reserved = await db.reserve_one(
            product, query.from_user.id, price, product["price"], "manual", promo_code
        )
        if reserved is None:
            await query.answer("Нет в наличии", show_alert=True)
            return
        await state.update_data(promo_code=None)  # промокод учтён в заказе
        await query.message.answer(
            texts.manual_invoice(product["title"], price, config.currency,
                                  config.payment_details, reserved["order_id"]),
            reply_markup=kb.manual_pay_kb(reserved["order_id"]),
        )
        await query.answer()
        return

    # stars / provider — счёт Telegram
    title = product["title"][:32]
    description = (product["description"] or product["title"])[:255]
    await query.message.answer_invoice(
        title=title,
        description=description,
        payload=_encode(product["id"], promo_code),
        currency=config.currency,
        prices=[LabeledPrice(label=title, amount=_invoice_amount(price, config))],
        provider_token=config.provider_token,
    )
    await query.answer()


@router.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery, db: Database) -> None:
    product_id, _ = _decode(pcq.invoice_payload)
    product = await db.get_product(product_id)
    if product is None or not product["is_active"] or await db.available_count(product["id"]) <= 0:
        await pcq.answer(ok=False, error_message="Извините, товар только что закончился.")
        return
    await pcq.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, bot: Bot, db: Database,
                                config: Config, state: FSMContext) -> None:
    sp = message.successful_payment
    user = message.from_user
    if sp is None or user is None:
        return

    charge_id = sp.telegram_payment_charge_id
    product_id, promo_code = _decode(sp.invoice_payload)
    product = await db.get_product(product_id)

    delivered = None
    if product is not None:
        delivered = await db.deliver_one(
            product, user.id, charge_id, sp.total_amount, product["price"], config.payment_method,
            promo_code,
        )

    if delivered is None:
        if config.is_stars:
            try:
                await bot.refund_star_payment(user_id=user.id, telegram_payment_charge_id=charge_id)
            except Exception:  # noqa: BLE001
                logger.exception("Не удалось вернуть оплату пользователю %s", user.id)
        await message.answer(texts.refunded_sold_out())
        await _notify_admins(
            bot, config,
            f"⚠️ Оплата без выдачи (наличие кончилось). Покупатель id{user.id}, charge {charge_id}.",
        )
        return

    if promo_code:
        await db.use_promocode(promo_code)
    await state.update_data(promo_code=None)

    await message.answer(texts.delivery(product["title"], delivered["payload"]))
    await _notify_admins(
        bot, config,
        texts.new_sale_admin(product["title"], user.id, user.username, sp.total_amount, config.currency),
    )


# ── Ручная оплата: действия покупателя ────────────────────────────────
@router.callback_query(PayCB.filter(F.action == "paid"))
async def cb_manual_paid(query: CallbackQuery, callback_data: PayCB, bot: Bot,
                         db: Database, config: Config) -> None:
    order = await db.get_order(callback_data.order_id)
    if order is None or order["status"] != "pending" or query.from_user is None \
            or order["user_id"] != query.from_user.id:
        await query.answer("Заказ не найден или уже обработан", show_alert=True)
        return
    if query.message:
        await query.message.edit_text(texts.manual_awaiting())
    await _notify_admins(
        bot, config,
        texts.admin_manual_request(order["id"], order["title"], order["price"],
                                   config.currency, query.from_user.id, query.from_user.username),
        markup=kb.admin_order_kb(order["id"]),
    )
    await query.answer()


@router.callback_query(PayCB.filter(F.action == "cancel"))
async def cb_manual_cancel(query: CallbackQuery, callback_data: PayCB, db: Database) -> None:
    order = await db.get_order(callback_data.order_id)
    if order and order["status"] == "pending" and query.from_user \
            and order["user_id"] == query.from_user.id:
        await db.reject_order(order["id"])
    if query.message:
        await query.message.edit_text(texts.manual_cancelled())
    await query.answer()
