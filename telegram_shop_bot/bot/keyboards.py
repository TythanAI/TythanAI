"""Inline-клавиатуры и callback-data фабрики."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import texts


class MenuCB(CallbackData, prefix="m"):
    action: str  # home, catalog, purchases, support, admin, promo, reviews


class CatCB(CallbackData, prefix="c"):
    cat_id: int  # 0 = корень каталога


class ProductCB(CallbackData, prefix="p"):
    action: str  # view, buy, reviews, review
    product_id: int
    back: int = 0  # категория, куда вернуться


class RateCB(CallbackData, prefix="rate"):
    product_id: int
    rating: int


class PayCB(CallbackData, prefix="pay"):
    action: str  # paid, cancel
    order_id: int


class PayMethodCB(CallbackData, prefix="pm"):
    method: str  # stars, provider, manual, ton
    product_id: int
    back: int = 0


class TonCheckCB(CallbackData, prefix="tc"):
    order_id: int


class AdminCB(CallbackData, prefix="a"):
    action: str  # panel, add_product, add_stock, list, stats, cats, promos, add_promo, broadcast, reviews


class AdminProductCB(CallbackData, prefix="ap"):
    action: str  # manage, pick_stock, toggle, delete
    product_id: int


class AdminCatCB(CallbackData, prefix="ac"):
    action: str  # nav, add, delete, prodcat
    cat_id: int = 0


class AdminOrderCB(CallbackData, prefix="ao"):
    action: str  # approve, reject
    order_id: int


class AdminPromoCB(CallbackData, prefix="apr"):
    action: str  # delete
    code: str


# ── Пользовательские клавиатуры ───────────────────────────────────────
def main_menu(is_admin: bool, has_support: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛍 Каталог", callback_data=CatCB(cat_id=0))
    kb.button(text="🎟 Промокод", callback_data=MenuCB(action="promo"))
    kb.button(text="🧾 Мои покупки", callback_data=MenuCB(action="purchases"))
    kb.button(text="⭐️ Отзывы", callback_data=MenuCB(action="reviews"))
    if has_support:
        kb.button(text="💬 Поддержка", callback_data=MenuCB(action="support"))
    if is_admin:
        kb.button(text="🛠 Админка", callback_data=MenuCB(action="admin"))
    kb.adjust(1, 2, 1)
    return kb.as_markup()


def catalog_screen(subcats, products, current_cat: int, back_cat: int, is_root: bool,
                   currency: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for c in subcats:
        kb.button(text=f"📁 {c['name']}", callback_data=CatCB(cat_id=c["id"]))
    sym = texts.currency_symbol(currency)
    for p in products:
        avail = p["available"]
        mark = f"{avail} шт." if avail > 0 else "нет"
        kb.button(
            text=f"{p['title']} — {p['price']}{sym} ({mark})",
            callback_data=ProductCB(action="view", product_id=p["id"], back=current_cat),
        )
    if is_root:
        kb.button(text="⬅️ В меню", callback_data=MenuCB(action="home"))
    else:
        kb.button(text="⬅️ Назад", callback_data=CatCB(cat_id=back_cat))
    kb.adjust(1)
    return kb.as_markup()


def product_view(product_id: int, available: int, price_label: str, back_cat: int,
                 has_reviews: bool, can_review: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if available > 0:
        kb.button(
            text=f"🛒 Купить за {price_label}",
            callback_data=ProductCB(action="buy", product_id=product_id, back=back_cat),
        )
    if has_reviews:
        kb.button(text="⭐️ Отзывы", callback_data=ProductCB(action="reviews", product_id=product_id, back=back_cat))
    if can_review:
        kb.button(text="✍️ Оставить отзыв", callback_data=ProductCB(action="review", product_id=product_id, back=back_cat))
    kb.button(text="⬅️ К каталогу", callback_data=CatCB(cat_id=back_cat))
    kb.adjust(1)
    return kb.as_markup()


def rating_kb(product_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for r in range(1, 6):
        kb.button(text="⭐️" * r, callback_data=RateCB(product_id=product_id, rating=r))
    kb.button(text="⬅️ Отмена", callback_data=ProductCB(action="view", product_id=product_id, back=0))
    kb.adjust(1)
    return kb.as_markup()


def payment_choice(product_id: int, methods: list[str], back_cat: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for m in methods:
        kb.button(
            text=texts.method_label(m),
            callback_data=PayMethodCB(method=m, product_id=product_id, back=back_cat),
        )
    kb.button(text="⬅️ Назад", callback_data=ProductCB(action="view", product_id=product_id, back=back_cat))
    kb.adjust(1)
    return kb.as_markup()


def manual_pay_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Я оплатил(а)", callback_data=PayCB(action="paid", order_id=order_id))
    kb.button(text="❌ Отменить заказ", callback_data=PayCB(action="cancel", order_id=order_id))
    kb.adjust(1)
    return kb.as_markup()


def ton_pay_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Я оплатил — проверить", callback_data=TonCheckCB(order_id=order_id))
    kb.button(text="❌ Отменить заказ", callback_data=PayCB(action="cancel", order_id=order_id))
    kb.adjust(1)
    return kb.as_markup()


def admin_order_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data=AdminOrderCB(action="approve", order_id=order_id))
    kb.button(text="❌ Отклонить", callback_data=AdminOrderCB(action="reject", order_id=order_id))
    kb.adjust(2)
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
    kb.button(text="🗂 Категории", callback_data=AdminCB(action="cats"))
    kb.button(text="🎟 Промокоды", callback_data=AdminCB(action="promos"))
    kb.button(text="📣 Рассылка", callback_data=AdminCB(action="broadcast"))
    kb.button(text="⭐️ Отзывы", callback_data=AdminCB(action="reviews"))
    kb.button(text="📊 Статистика", callback_data=AdminCB(action="stats"))
    kb.button(text="💾 Бэкап базы", callback_data=AdminCB(action="backup"))
    kb.button(text="⬅️ В меню", callback_data=MenuCB(action="home"))
    kb.adjust(2, 2, 2, 2, 1)
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


def category_picker(categories, path_of) -> InlineKeyboardMarkup:
    """Выбор категории при создании товара (плоский список с путём)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🚫 Без категории", callback_data=AdminCatCB(action="prodcat", cat_id=0))
    for c in categories:
        kb.button(text=f"📁 {path_of(c['id'])}", callback_data=AdminCatCB(action="prodcat", cat_id=c["id"]))
    kb.adjust(1)
    return kb.as_markup()


def admin_categories_screen(current_id: int, subcats) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for c in subcats:
        kb.button(text=f"📁 {c['name']}", callback_data=AdminCatCB(action="nav", cat_id=c["id"]))
    kb.button(text="➕ Добавить категорию здесь", callback_data=AdminCatCB(action="add", cat_id=current_id))
    if current_id:
        kb.button(text="🗑 Удалить эту категорию", callback_data=AdminCatCB(action="delete", cat_id=current_id))
    kb.button(text="⬅️ В админку", callback_data=MenuCB(action="admin"))
    kb.adjust(1)
    return kb.as_markup()


def admin_promos_list(promos) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in promos:
        kb.button(text=f"🗑 {p['code']}", callback_data=AdminPromoCB(action="delete", code=p["code"]))
    kb.button(text="➕ Новый промокод", callback_data=AdminCB(action="add_promo"))
    kb.button(text="⬅️ В админку", callback_data=MenuCB(action="admin"))
    kb.adjust(1)
    return kb.as_markup()


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Отправить всем", callback_data=AdminCB(action="broadcast_send"))
    kb.button(text="⬅️ Отмена", callback_data=MenuCB(action="admin"))
    kb.adjust(1)
    return kb.as_markup()
