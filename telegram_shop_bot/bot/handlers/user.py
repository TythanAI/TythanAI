"""Пользовательские обработчики: меню, каталог, карточка товара, покупки."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..config import Config
from ..database import Database
from ..keyboards import MenuCB, ProductCB
from ..utils import render

router = Router(name="user")


async def show_menu(event: Message | CallbackQuery, config: Config) -> None:
    is_admin = config.is_admin(event.from_user.id if event.from_user else None)
    await render(
        event,
        texts.welcome(config.shop_name),
        kb.main_menu(is_admin=is_admin, has_support=bool(config.support_contact)),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, config: Config) -> None:
    user = message.from_user
    if user:
        await db.upsert_user(user.id, user.username, user.first_name)
    await show_menu(message, config)


@router.message(Command("help"))
async def cmd_help(message: Message, config: Config) -> None:
    await show_menu(message, config)


@router.callback_query(MenuCB.filter(F.action == "home"))
async def cb_home(query: CallbackQuery, config: Config) -> None:
    await show_menu(query, config)
    await query.answer()


@router.callback_query(MenuCB.filter(F.action == "catalog"))
async def cb_catalog(query: CallbackQuery, db: Database, config: Config) -> None:
    products = await db.list_products(only_active=True)
    if not products:
        await render(query, texts.catalog_empty(), kb.back_to_menu())
    else:
        await render(query, texts.catalog_header(), kb.catalog(products, config.currency))
    await query.answer()


@router.callback_query(ProductCB.filter(F.action == "view"))
async def cb_view_product(
    query: CallbackQuery, callback_data: ProductCB, db: Database, config: Config
) -> None:
    product = await db.get_product(callback_data.product_id)
    if product is None or not product["is_active"]:
        await query.answer("Товар недоступен", show_alert=True)
        return
    available = await db.available_count(product["id"])
    price_label = texts.price_str(product["price"], config.currency)
    await render(
        query,
        texts.product_card(product, available, config.currency),
        kb.product_view(product["id"], available, price_label),
    )
    await query.answer()


@router.callback_query(MenuCB.filter(F.action == "purchases"))
async def cb_purchases(query: CallbackQuery, db: Database, config: Config) -> None:
    if query.from_user is None:
        return
    orders = await db.get_user_orders(query.from_user.id)
    if not orders:
        await render(query, texts.purchases_empty(), kb.back_to_menu())
    else:
        lines = [texts.purchases_header()]
        lines += [texts.purchase_line(o, config.currency) for o in orders]
        await render(query, "\n".join(lines), kb.back_to_menu())
    await query.answer()


@router.callback_query(MenuCB.filter(F.action == "support"))
async def cb_support(query: CallbackQuery, config: Config) -> None:
    await render(query, texts.support(config.support_contact), kb.back_to_menu())
    await query.answer()


@router.message()
async def fallback(message: Message, config: Config) -> None:
    """Любое непонятое сообщение — показываем меню.

    Роутер user подключается последним, поэтому команды, шаги админки и
    сообщения об оплате уже обработаны более специфичными хендлерами.
    """
    await show_menu(message, config)
