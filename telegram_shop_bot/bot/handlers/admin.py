"""Админ-панель. Весь роутер защищён фильтром IsAdmin."""

from __future__ import annotations

import asyncio
import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..config import Config
from ..database import Database
from ..filters import IsAdmin
from ..keyboards import (
    AdminCatCB,
    AdminCB,
    AdminOrderCB,
    AdminProductCB,
    AdminPromoCB,
    MenuCB,
)
from ..services.backup import send_backup
from ..services.orders import approve_and_deliver
from ..states import AddCategory, AddProduct, AddPromo, AddStock, Broadcast
from ..utils import render

logger = logging.getLogger(__name__)
router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

_CODE_RE = re.compile(r"^[A-Z0-9_-]{1,32}$")


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
    await render(query, texts.admin_stats(await db.stats(), config.currency), kb.admin_back())
    await query.answer()


@router.callback_query(AdminCB.filter(F.action == "backup"))
async def cb_backup(query: CallbackQuery, bot: Bot, db: Database, config: Config) -> None:
    if query.from_user is None:
        return
    # если чат для бэкапов не задан — присылаем файл самому админу
    to_self = config.backup_chat_id is None
    chat = query.from_user.id if to_self else config.backup_chat_id
    await query.answer("Делаю бэкап…")
    try:
        ok = await send_backup(bot, config, db, chat_id=chat)
        text = texts.backup_ok(to_self) if ok else texts.backup_failed()
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка бэкапа")
        text = texts.backup_failed()
    await render(query, text, kb.admin_back())


# ── добавление товара ─────────────────────────────────────────────────
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
async def add_product_desc(message: Message, state: FSMContext, config: Config) -> None:
    text = (message.text or "").strip()
    await state.update_data(description="" if text == "-" else text)
    await state.set_state(AddProduct.price)
    await message.answer(texts.add_product_price(config.currency))


@router.message(AddProduct.price)
async def add_product_price(message: Message, state: FSMContext, db: Database) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer(texts.error_price())
        return
    await state.update_data(price=int(raw))

    cats = await db.all_categories()
    if not cats:
        await _finish_product(message, state, db, category_id=None)
        return

    paths = {c["id"]: await db.category_path(c["id"]) for c in cats}
    await state.set_state(AddProduct.category)
    await message.answer(
        texts.add_product_category(),
        reply_markup=kb.category_picker(cats, lambda cid: paths.get(cid, "")),
    )


@router.callback_query(AdminCatCB.filter(F.action == "prodcat"), AddProduct.category)
async def cb_pick_product_category(query: CallbackQuery, callback_data: AdminCatCB,
                                   state: FSMContext, db: Database) -> None:
    category_id = callback_data.cat_id or None
    if query.message:
        await _finish_product(query.message, state, db, category_id=category_id, edit=True)
    await query.answer()


async def _finish_product(message: Message, state: FSMContext, db: Database,
                          category_id: int | None, edit: bool = False) -> None:
    data = await state.get_data()
    product_id = await db.add_product(
        title=data["title"], description=data.get("description", ""),
        category_id=category_id, price=int(data["price"]),
    )
    await state.clear()
    text = texts.product_created(product_id, data["title"])
    if edit:
        await message.edit_text(text, reply_markup=kb.admin_panel())
    else:
        await message.answer(text, reply_markup=kb.admin_panel())


# ── добавление наличия ────────────────────────────────────────────────
@router.callback_query(AdminCB.filter(F.action == "add_stock"))
async def cb_add_stock(query: CallbackQuery, db: Database) -> None:
    products = await db.list_all_products(only_active=False)
    if not products:
        await render(query, texts.no_products_yet(), kb.admin_back())
    else:
        await render(query, texts.choose_product_for_stock(), kb.admin_products_for_stock(products))
    await query.answer()


@router.callback_query(AdminProductCB.filter(F.action == "pick_stock"))
async def cb_pick_stock(query: CallbackQuery, callback_data: AdminProductCB,
                        state: FSMContext, db: Database) -> None:
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
    product = await db.get_product(data.get("product_id"))
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
    await message.answer(texts.stock_added(added, product["title"]), reply_markup=kb.admin_panel())


# ── список товаров и управление ───────────────────────────────────────
@router.callback_query(AdminCB.filter(F.action == "list"))
async def cb_list(query: CallbackQuery, db: Database) -> None:
    products = await db.list_all_products(only_active=False)
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
    cat_path = await db.category_path(product["category_id"])
    await render(
        query,
        texts.admin_product_manage(product, available, config.currency, cat_path or None),
        kb.admin_product_manage(product),
    )


@router.callback_query(AdminProductCB.filter(F.action == "manage"))
async def cb_manage(query: CallbackQuery, callback_data: AdminProductCB, db: Database,
                    config: Config) -> None:
    await _show_manage(query, db, config, callback_data.product_id)
    await query.answer()


@router.callback_query(AdminProductCB.filter(F.action == "toggle"))
async def cb_toggle(query: CallbackQuery, callback_data: AdminProductCB, db: Database,
                    config: Config) -> None:
    product = await db.get_product(callback_data.product_id)
    if product is None:
        await query.answer("Товар не найден", show_alert=True)
        return
    await db.set_product_active(product["id"], not product["is_active"])
    await _show_manage(query, db, config, product["id"])
    await query.answer("Готово")


@router.callback_query(AdminProductCB.filter(F.action == "delete"))
async def cb_delete(query: CallbackQuery, callback_data: AdminProductCB, db: Database) -> None:
    await db.delete_product(callback_data.product_id)
    products = await db.list_all_products(only_active=False)
    if not products:
        await render(query, texts.no_products_yet(), kb.admin_back())
    else:
        await render(query, texts.admin_products_header(), kb.admin_products_list(products))
    await query.answer("Товар удалён")


# ── категории ─────────────────────────────────────────────────────────
async def _show_categories(query: CallbackQuery, db: Database, cat_id: int) -> None:
    subcats = await db.list_categories(parent_id=None if cat_id == 0 else cat_id)
    path = await db.category_path(cat_id) if cat_id else None
    await render(query, texts.admin_cats_header(path or None), kb.admin_categories_screen(cat_id, subcats))


@router.callback_query(AdminCB.filter(F.action == "cats"))
async def cb_cats(query: CallbackQuery, db: Database) -> None:
    await _show_categories(query, db, 0)
    await query.answer()


@router.callback_query(AdminCatCB.filter(F.action == "nav"))
async def cb_cat_nav(query: CallbackQuery, callback_data: AdminCatCB, db: Database) -> None:
    await _show_categories(query, db, callback_data.cat_id)
    await query.answer()


@router.callback_query(AdminCatCB.filter(F.action == "add"))
async def cb_cat_add(query: CallbackQuery, callback_data: AdminCatCB, state: FSMContext) -> None:
    await state.set_state(AddCategory.name)
    await state.update_data(parent_id=callback_data.cat_id or None)
    if query.message:
        await query.message.answer(texts.ask_category_name())
    await query.answer()


@router.message(AddCategory.name)
async def on_category_name(message: Message, state: FSMContext, db: Database) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым. Введи название категории:")
        return
    data = await state.get_data()
    await db.add_category(name, data.get("parent_id"))
    await state.clear()
    await message.answer(texts.category_added(name), reply_markup=kb.admin_panel())


@router.callback_query(AdminCatCB.filter(F.action == "delete"))
async def cb_cat_delete(query: CallbackQuery, callback_data: AdminCatCB, db: Database) -> None:
    await db.delete_category(callback_data.cat_id)
    await render(query, texts.category_deleted(), kb.admin_back())
    await query.answer("Удалено")


# ── промокоды ─────────────────────────────────────────────────────────
@router.callback_query(AdminCB.filter(F.action == "promos"))
async def cb_promos(query: CallbackQuery, db: Database) -> None:
    promos = await db.list_promocodes()
    lines = [texts.promos_header()]
    lines += [texts.promo_line(p) for p in promos] or ["—"]
    await render(query, "\n".join(lines), kb.admin_promos_list(promos))
    await query.answer()


@router.callback_query(AdminCB.filter(F.action == "add_promo"))
async def cb_add_promo(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddPromo.code)
    if query.message:
        await query.message.answer(texts.ask_promo_code())
    await query.answer()


@router.message(AddPromo.code)
async def on_promo_code_input(message: Message, state: FSMContext, db: Database) -> None:
    code = (message.text or "").strip().upper()
    if not _CODE_RE.match(code):
        await message.answer("⚠️ Только латиница/цифры/-/_ (до 32 символов). Введи код ещё раз:")
        return
    if await db.get_promocode(code) is not None:
        await message.answer(texts.promo_code_exists())
        return
    await state.update_data(code=code)
    await state.set_state(AddPromo.discount)
    await message.answer(texts.ask_promo_discount())


@router.message(AddPromo.discount)
async def on_promo_discount(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if raw.endswith("%"):
        val = raw[:-1].strip()
        if not (val.isdigit() and 1 <= int(val) <= 100):
            await message.answer(texts.promo_bad_discount())
            return
        await state.update_data(discount_type="percent", discount_value=int(val))
    elif raw.isdigit() and int(raw) > 0:
        await state.update_data(discount_type="fixed", discount_value=int(raw))
    else:
        await message.answer(texts.promo_bad_discount())
        return
    await state.set_state(AddPromo.limit)
    await message.answer(texts.ask_promo_limit())


@router.message(AddPromo.limit)
async def on_promo_limit(message: Message, state: FSMContext, db: Database) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("⚠️ Введи число (0 — без лимита):")
        return
    data = await state.get_data()
    await db.add_promocode(
        code=data["code"], discount_type=data["discount_type"],
        discount_value=int(data["discount_value"]), max_uses=int(raw),
    )
    await state.clear()
    await message.answer(texts.promo_created(data["code"]), reply_markup=kb.admin_panel())


@router.callback_query(AdminPromoCB.filter(F.action == "delete"))
async def cb_promo_delete(query: CallbackQuery, callback_data: AdminPromoCB, db: Database) -> None:
    await db.delete_promocode(callback_data.code)
    promos = await db.list_promocodes()
    lines = [texts.promos_header()]
    lines += [texts.promo_line(p) for p in promos] or ["—"]
    await render(query, "\n".join(lines), kb.admin_promos_list(promos))
    await query.answer("Удалён")


# ── рассылка ──────────────────────────────────────────────────────────
@router.callback_query(AdminCB.filter(F.action == "broadcast"))
async def cb_broadcast(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Broadcast.message)
    if query.message:
        await query.message.answer(texts.broadcast_ask())
    await query.answer()


@router.message(Broadcast.message)
async def on_broadcast_message(message: Message, state: FSMContext, db: Database) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer(texts.broadcast_empty())
        return
    count = len(await db.all_user_ids())
    await state.update_data(broadcast_text=text)
    await state.set_state(Broadcast.confirm)
    await message.answer(texts.broadcast_preview(text, count), reply_markup=kb.broadcast_confirm_kb())


@router.callback_query(AdminCB.filter(F.action == "broadcast_send"), Broadcast.confirm)
async def cb_broadcast_send(query: CallbackQuery, state: FSMContext, bot: Bot, db: Database) -> None:
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    await state.clear()
    if query.message:
        await query.message.edit_text("📣 Отправляю…")
    ok = failed = 0
    for uid in await db.all_user_ids():
        try:
            await bot.send_message(uid, text)
            ok += 1
        except Exception:  # noqa: BLE001 — заблокировавшие бота и т.п.
            failed += 1
        await asyncio.sleep(0.05)  # бережём лимиты Telegram (~30 msg/s)
    await bot.send_message(query.from_user.id, texts.broadcast_done(ok, failed), reply_markup=kb.admin_panel())
    await query.answer()


# ── отзывы (просмотр) ─────────────────────────────────────────────────
@router.callback_query(AdminCB.filter(F.action == "reviews"))
async def cb_admin_reviews(query: CallbackQuery, db: Database) -> None:
    reviews = await db.list_recent_reviews()
    if not reviews:
        await render(query, texts.reviews_empty(), kb.admin_back())
    else:
        lines = [texts.admin_reviews_header()]
        lines += [texts.review_line(r, with_product=True) for r in reviews]
        await render(query, "\n\n".join(lines), kb.admin_back())
    await query.answer()


# ── подтверждение ручной оплаты ───────────────────────────────────────
@router.callback_query(AdminOrderCB.filter(F.action == "approve"))
async def cb_order_approve(query: CallbackQuery, callback_data: AdminOrderCB, bot: Bot,
                           db: Database, config: Config) -> None:
    result = await approve_and_deliver(bot, config, db, callback_data.order_id)
    if result is None:
        await query.answer("Заказ уже обработан или наличие пропало", show_alert=True)
        if query.message:
            await query.message.edit_text("⚠️ Заказ уже обработан.")
        return
    if query.message:
        await query.message.edit_text(f"✅ Заказ #{result['order_id']} подтверждён, товар выдан.")
    await query.answer("Подтверждено")


@router.callback_query(AdminOrderCB.filter(F.action == "reject"))
async def cb_order_reject(query: CallbackQuery, callback_data: AdminOrderCB, bot: Bot,
                          db: Database) -> None:
    order = await db.reject_order(callback_data.order_id)
    if order is None:
        await query.answer("Заказ уже обработан", show_alert=True)
        if query.message:
            await query.message.edit_text("⚠️ Заказ уже обработан.")
        return
    try:
        await bot.send_message(order["user_id"], texts.manual_rejected())
    except Exception:  # noqa: BLE001
        logger.warning("Не удалось уведомить покупателя %s об отклонении", order["user_id"])
    if query.message:
        await query.message.edit_text(f"❌ Заказ #{order['id']} отклонён, резерв снят.")
    await query.answer("Отклонено")
