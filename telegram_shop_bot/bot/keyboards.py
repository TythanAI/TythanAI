"""Inline-клавиатуры и callback-data фабрики."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import texts


class MenuCB(CallbackData, prefix="menu"):
    action: str  # home, catalog, purchases, support, admin


class ProductCB(CallbackData, prefix="prod"):
    action: str  # view, buy
    product_id: int


class AdminCB(CallbackData, prefix="adm"):
    action: str  # panel, add_product, add_stock, list, stats
    product_id: int = 0


class AdminProductCB(CallbackData, prefix="admp"):
    action: str  # manage, pick_stock, toggle, delete
    product_id: int


# ── Пользовательские клавиатуры ───────────────────────────────────────
def main_menu(is_admin: bool, has_support: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛍 Каталог", callback_data=MenuCB(action="catalog"))
    kb.button(text="🧾 Мои покупки", callback_data=MenuCB(action="purchases"))
    if has_support:
        kb.button(text="💬 Поддержка", callback_data=MenuCB(action="support"))
    if is_admin:
        kb.button(text="🛠 Админка", callback_data=MenuCB(action="admin"))
    kb.adjust(1)
    return kb.as_markup()


def catalog(products, currency: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    cur = texts.currency_label(currency)
    for p in products:
        avail = p["available"]
        mark = f"{avail} шт." if avail > 0 else "нет"
        kb.button(
            text=f"{p['title']} — {p['price']}{cur} ({mark})",
            callback_data=ProductCB(action="view", product_id=p["id"]),
        )
    kb.button(text="⬅️ В меню", callback_data=MenuCB(action="home"))
    kb.adjust(1)
    return kb.as_markup()


def product_view(product_id: int, available: int, price_label: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if available > 0:
        kb.button(
            text=f"🛒 Купить за {price_label}",
            callback_data=ProductCB(action="buy", product_id=product_id),
        )
    kb.button(text="⬅️ К каталогу", callback_data=MenuCB(action="catalog"))
    kb.adjust(1)
    return kb.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В меню", callback_data=MenuCB(action="home"))
    return kb.as_markup()


# ── Админские клавиатуры ──────────────────────────────────────────────
def admin_panel() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить товар", callback_data=AdminCB(action="add_product"))
    kb.button(text="📦 Добавить наличие", callback_data=AdminCB(action="add_stock"))
    kb.button(text="📋 Товары", callback_data=AdminCB(action="list"))
    kb.button(text="📊 Статистика", callback_data=AdminCB(action="stats"))
    kb.button(text="⬅️ В меню", callback_data=MenuCB(action="home"))
    kb.adjust(1)
    return kb.as_markup()


def admin_back() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В админку", callback_data=MenuCB(action="admin"))
    return kb.as_markup()


def admin_products_for_stock(products) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(
            text=f"{p['title']} (в наличии: {p['available']})",
            callback_data=AdminProductCB(action="pick_stock", product_id=p["id"]),
        )
    kb.button(text="⬅️ В админку", callback_data=MenuCB(action="admin"))
    kb.adjust(1)
    return kb.as_markup()


def admin_products_list(products) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in products:
        flag = "🟢" if p["is_active"] else "🔴"
        kb.button(
            text=f"{flag} {p['title']} ({p['available']} шт.)",
            callback_data=AdminProductCB(action="manage", product_id=p["id"]),
        )
    kb.button(text="⬅️ В админку", callback_data=MenuCB(action="admin"))
    kb.adjust(1)
    return kb.as_markup()


def admin_product_manage(product) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    pid = product["id"]
    toggle_text = "🔴 Скрыть" if product["is_active"] else "🟢 Показать"
    kb.button(text=toggle_text, callback_data=AdminProductCB(action="toggle", product_id=pid))
    kb.button(text="📦 Добавить наличие", callback_data=AdminProductCB(action="pick_stock", product_id=pid))
    kb.button(text="🗑 Удалить товар", callback_data=AdminProductCB(action="delete", product_id=pid))
    kb.button(text="⬅️ К списку", callback_data=AdminCB(action="list"))
    kb.adjust(1)
    return kb.as_markup()
