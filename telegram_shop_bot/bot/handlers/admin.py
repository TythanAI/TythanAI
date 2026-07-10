"""Админ-панель: добавление товаров и наличия, список товаров, статистика.

Весь роутер защищён фильтром IsAdmin — обычные пользователи сюда не попадают.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..config import Config
from ..database import Database
from ..filters import IsAdmin
from ..keyboards import AdminCB, AdminProductCB, MenuCB
from ..states import AddProduct, AddStock
from ..utils import render

router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


# ── вход в панель / отмена ────────────────────────────────────────────
@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.cancelled(), reply_markup=kb.admin_panel())


@router.message(Command("admin"), StateFilter(None))
async def cmd_admin(message: Message) -> None:
    await message.answer(texts.admin_panel(), reply_markup=kb.admin_panel())


@router.callback_query(MenuCB.filter(F.action == "admin"))
async def cb_admin(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await render(query, texts.admin_panel(), kb.admin_panel())
    await query.answer()


@router.callback_query(AdminCB.filter(F.action == "stats"))
async def cb_stats(query: CallbackQuery, db: Database, config: Config) -> None:
    stats = await db.stats()
    await render(query, texts.admin_stats(stats, config.currency), kb.admin_back())
    await query.answer()


# ── добавление товара (FSM) ───────────────────────────────────────────
@router.callback_query(AdminCB.filter(F.action == "add_product"))
async def cb_add_product(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddProduct.title)
    if query.message:
        await query.message.answer(texts.ADD_PRODUCT_TITLE)
    await query.answer()


@router.message(AddProduct.title)
async def add_product_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым. Введи название:")
        return
    await state.update_data(title=title)
    await state.set_state(AddProduct.description)
    await message.answer(texts.ADD_PRODUCT_DESC)


@router.message(AddProduct.description)
async def add_product_desc(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    description = "" if text == "-" else text
    await state.update_data(description=description)
    await state.set_state(AddProduct.category)
    await message.answer(texts.ADD_PRODUCT_CATEGORY)


@router.message(AddProduct.category)
async def add_product_category(message: Message, state: FSMContext, config: Config) -> None:
    text = (message.text or "").strip()
    category = "" if text == "-" else text
    await state.update_data(category=category)
    await state.set_state(AddProduct.price)
    await message.answer(texts.add_product_price(config.currency))


@router.message(AddProduct.price)
async def add_product_price(message: Message, state: FSMContext, db: Database) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer(texts.error_price())
        return
    data = await state.get_data()
    product_id = await db.add_product(
        title=data["title"],
        description=data.get("description", ""),
        category=data.get("category", ""),
        price=int(raw),
    )
    await state.clear()
    await message.answer(
        texts.product_created(product_id, data["title"]),
        reply_markup=kb.admin_panel(),
    )


# ── добавление наличия (FSM) ──────────────────────────────────────────
@router.callback_query(AdminCB.filter(F.action == "add_stock"))
async def cb_add_stock(query: CallbackQuery, db: Database) -> None:
    products = await db.list_products(only_active=False)
    if not products:
        await render(query, texts.no_products_yet(), kb.admin_back())
    else:
        await render(query, texts.choose_product_for_stock(), kb.admin_products_for_stock(products))
    await query.answer()


@router.callback_query(AdminProductCB.filter(F.action == "pick_stock"))
async def cb_pick_stock(
    query: CallbackQuery, callback_data: AdminProductCB, state: FSMContext, db: Database
) -> None:
    product = await db.get_product(callback_data.product_id)
    if product is None:
        await query.answer("Товар не найден", show_alert=True)
        return
    await state.set_state(AddStock.waiting_items)
    await state.update_data(product_id=product["id"])
    if query.message:
        await query.message.answer(texts.ask_stock_items(product["title"]))
    await query.answer()


@router.message(AddStock.waiting_items)
async def add_stock_items(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    product_id = data.get("product_id")
    product = await db.get_product(product_id) if product_id else None
    if product is None:
        await state.clear()
        await message.answer("Товар не найден. Начни заново.", reply_markup=kb.admin_panel())
        return
    items = [line.strip() for line in (message.text or "").splitlines() if line.strip()]
    if not items:
        await message.answer("Пусто. Пришли хотя бы одну строку или /cancel.")
        return
    added = await db.add_stock(product["id"], items)
    await state.clear()
    await message.answer(
        texts.stock_added(added, product["title"]), reply_markup=kb.admin_panel()
    )


# ── список товаров и управление ───────────────────────────────────────
@router.callback_query(AdminCB.filter(F.action == "list"))
async def cb_list(query: CallbackQuery, db: Database) -> None:
    products = await db.list_products(only_active=False)
    if not products:
        await render(query, texts.no_products_yet(), kb.admin_back())
    else:
        await render(query, texts.admin_products_header(), kb.admin_products_list(products))
    await query.answer()


async def _show_manage(query: CallbackQuery, db: Database, config: Config, product_id: int) -> None:
    product = await db.get_product(product_id)
    if product is None:
        await query.answer("Товар не найден", show_alert=True)
        return
    available = await db.available_count(product["id"])
    await render(
        query,
        texts.admin_product_manage(product, available, config.currency),
        kb.admin_product_manage(product),
    )


@router.callback_query(AdminProductCB.filter(F.action == "manage"))
async def cb_manage(
    query: CallbackQuery, callback_data: AdminProductCB, db: Database, config: Config
) -> None:
    await _show_manage(query, db, config, callback_data.product_id)
    await query.answer()


@router.callback_query(AdminProductCB.filter(F.action == "toggle"))
async def cb_toggle(
    query: CallbackQuery, callback_data: AdminProductCB, db: Database, config: Config
) -> None:
    product = await db.get_product(callback_data.product_id)
    if product is None:
        await query.answer("Товар не найден", show_alert=True)
        return
    await db.set_product_active(product["id"], not product["is_active"])
    await _show_manage(query, db, config, product["id"])
    await query.answer("Готово")


@router.callback_query(AdminProductCB.filter(F.action == "delete"))
async def cb_delete(
    query: CallbackQuery, callback_data: AdminProductCB, db: Database
) -> None:
    await db.delete_product(callback_data.product_id)
    products = await db.list_products(only_active=False)
    if not products:
        await render(query, texts.no_products_yet(), kb.admin_back())
    else:
        await render(query, texts.admin_products_header(), kb.admin_products_list(products))
    await query.answer("Товар удалён")
