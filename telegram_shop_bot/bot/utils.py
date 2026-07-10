"""Вспомогательные функции для обработчиков."""

from __future__ import annotations

from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


def apply_discount(price: int, promo: Any | None) -> int:
    """Цена со скидкой по промокоду. Минимум 1 (иначе оплата невозможна)."""
    if promo is None:
        return price
    if promo["discount_type"] == "percent":
        discounted = price - price * int(promo["discount_value"]) // 100
    else:  # fixed
        discounted = price - int(promo["discount_value"])
    return max(1, discounted)


def promo_label(promo: Any) -> str:
    if promo["discount_type"] == "percent":
        return f"-{promo['discount_value']}%"
    return f"-{promo['discount_value']}"


async def active_promo(state: Any, db: Any):
    """Промокод, применённый покупателем (из FSM-данных), если он ещё валиден.
    Невалидный код тихо снимается."""
    data = await state.get_data()
    code = data.get("promo_code")
    if not code:
        return None
    promo = await db.valid_promocode(code)
    if promo is None:
        await state.update_data(promo_code=None)
    return promo


async def render(
    event: Message | CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Показать экран: для callback — отредактировать сообщение, для обычного
    сообщения — отправить новое. Тихо игнорирует «сообщение не изменилось».
    """
    if isinstance(event, CallbackQuery):
        message = event.message
        if message is None:
            return
        try:
            await message.edit_text(text, reply_markup=reply_markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
    else:
        await event.answer(text, reply_markup=reply_markup)
