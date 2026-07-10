"""Мелкие помощники для обработчиков."""

from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


async def render(event: Message | CallbackQuery, text: str,
                 reply_markup: InlineKeyboardMarkup | None = None) -> None:
    if isinstance(event, CallbackQuery):
        if event.message is None:
            return
        try:
            await event.message.edit_text(text, reply_markup=reply_markup,
                                          disable_web_page_preview=True)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
    else:
        await event.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)
