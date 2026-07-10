"""Фильтры доступа."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from .config import Config


class IsAdmin(BaseFilter):
    """Пропускает событие, только если отправитель — администратор из ADMIN_IDS.

    `config` приходит из workflow-data диспетчера (см. run.py).
    """

    async def __call__(self, event: TelegramObject, config: Config | None = None) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and config and config.is_admin(user.id))
