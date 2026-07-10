"""Единая логика подтверждения заказа и выдачи товара покупателю.

Используется и при ручном подтверждении админом, и при авто-подтверждении
крипто-оплаты (TON). Держим в одном месте, чтобы выдача была одинаковой.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from aiogram import Bot

from .. import texts
from ..config import Config
from ..database import Database

logger = logging.getLogger(__name__)


async def approve_and_deliver(
    bot: Bot, config: Config, db: Database, order_id: int
) -> Optional[dict[str, Any]]:
    """Подтвердить pending-заказ, выдать товар покупателю, уведомить админов.
    Возвращает данные заказа или None, если заказ уже обработан / наличие пропало.
    """
    result = await db.approve_order(order_id)
    if result is None:
        return None

    if result["promo_code"]:
        await db.use_promocode(result["promo_code"])

    try:
        await bot.send_message(result["user_id"], texts.delivery(result["title"], result["payload"]))
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось выдать товар покупателю %s", result["user_id"])

    for admin_id in config.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                texts.new_sale_admin(result["title"], result["user_id"], None,
                                     result["price"], config.currency),
            )
        except Exception:  # noqa: BLE001
            logger.warning("Не удалось уведомить админа %s о продаже", admin_id)

    return result
