"""Вспомогательные функции для обработчиков."""

from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


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
