"""Все тексты, которые видит пользователь. Меняй их здесь — код трогать не нужно."""

from __future__ import annotations

from html import escape


def currency_label(currency: str) -> str:
    return "⭐" if currency.upper() == "XTR" else currency.upper()


def price_str(amount: int, currency: str) -> str:
    return f"{amount} {currency_label(currency)}"


def welcome(shop_name: str) -> str:
    return (
        f"👋 Добро пожаловать в <b>{escape(shop_name)}</b>!\n\n"
        "Здесь можно купить товары автоматически — оплата и выдача проходят прямо в боте.\n\n"
        "Выбери действие в меню ниже 👇"
    )


def catalog_empty() -> str:
    return "🛒 Каталог пока пуст. Загляни позже!"


def catalog_header() -> str:
    return "🛍 <b>Каталог</b>\n\nВыбери товар, чтобы посмотреть описание:"


def product_card(product, available: int, currency: str) -> str:
    title = escape(product["title"])
    desc = escape(product["description"]) if product["description"] else "—"
    cat = escape(product["category"]) if product["category"] else None
    lines = [f"📦 <b>{title}</b>", ""]
    if cat:
        lines.append(f"🏷 Категория: {cat}")
    lines.append(f"💵 Цена: <b>{price_str(product['price'], currency)}</b>")
    if available > 0:
        lines.append(f"✅ В наличии: <b>{available}</b> шт.")
    else:
        lines.append("⛔️ Нет в наличии")
    lines += ["", f"📝 {desc}"]
    return "\n".join(lines)


def out_of_stock() -> str:
    return "⛔️ К сожалению, этот товар только что закончился."


def delivery(product_title: str, payload: str) -> str:
    return (
        "✅ <b>Оплата получена. Спасибо за покупку!</b>\n\n"
        f"📦 {escape(product_title)}\n\n"
        "Твой товар:\n"
        f"<code>{escape(payload)}</code>\n\n"
        "Он также сохранён в разделе «🧾 Мои покупки»."
    )


def refunded_sold_out() -> str:
    return (
        "😔 Пока шла оплата, товар успели купить, и он закончился.\n"
        "Оплата (звёзды) <b>полностью возвращена</b> вам автоматически. "
        "Приносим извинения!"
    )


def purchases_empty() -> str:
    return "🧾 У тебя пока нет покупок."


def purchases_header() -> str:
    return "🧾 <b>Твои покупки</b>\n"


def purchase_line(order, currency: str) -> str:
    payload = order["payload"] if order["payload"] else "—"
    return (
        f"• <b>{escape(order['title'])}</b> — {price_str(order['price'], currency)}\n"
        f"  <code>{escape(payload)}</code>"
    )


def support(contact: str) -> str:
    if not contact:
        return "💬 Раздел поддержки пока не настроен."
    return f"💬 <b>Поддержка</b>\n\nПо всем вопросам пиши: {escape(contact)}"


# ── Админка ───────────────────────────────────────────────────────────
def admin_panel() -> str:
    return "🛠 <b>Админ-панель</b>\n\nВыбери действие:"


def admin_stats(s: dict, currency: str) -> str:
    return (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{s['users']}</b>\n"
        f"🧾 Продаж: <b>{s['orders']}</b>\n"
        f"💰 Выручка: <b>{price_str(s['revenue'], currency)}</b>\n"
        f"📦 Единиц в наличии: <b>{s['stock']}</b>"
    )


ADD_PRODUCT_TITLE = "➕ <b>Новый товар</b>\n\nШаг 1/4. Введи <b>название</b> товара:"
ADD_PRODUCT_DESC = "Шаг 2/4. Введи <b>описание</b> (или отправь «-», чтобы пропустить):"
ADD_PRODUCT_CATEGORY = "Шаг 3/4. Введи <b>категорию</b> (или «-», чтобы пропустить):"


def add_product_price(currency: str) -> str:
    unit = "звёздах (целое число, минимум 1)" if currency.upper() == "XTR" else f"{currency}"
    return f"Шаг 4/4. Введи <b>цену</b> в {unit}:"


def product_created(product_id: int, title: str) -> str:
    return (
        f"✅ Товар создан: <b>{escape(title)}</b> (ID {product_id}).\n\n"
        "Теперь добавь в него «наличие» — кнопка «📦 Добавить наличие» в админ-панели."
    )


def choose_product_for_stock() -> str:
    return "📦 <b>Добавить наличие</b>\n\nВыбери товар:"


def ask_stock_items(title: str) -> str:
    return (
        f"📦 Товар: <b>{escape(title)}</b>\n\n"
        "Пришли единицы наличия — <b>по одной на строку</b>.\n"
        "Например, по одному аккаунту в строке:\n"
        "<code>login1:pass1\nlogin2:pass2\nlogin3:pass3</code>\n\n"
        "Каждая строка станет отдельным товаром, который бот выдаст покупателю.\n"
        "Отправь /cancel, чтобы отменить."
    )


def stock_added(count: int, title: str) -> str:
    return f"✅ Добавлено единиц наличия: <b>{count}</b> в товар «{escape(title)}»."


def no_products_yet() -> str:
    return "Товаров пока нет. Сначала создай товар кнопкой «➕ Добавить товар»."


def admin_products_header() -> str:
    return "📋 <b>Товары</b>\n\nНажми на товар, чтобы управлять им:"


def admin_product_manage(product, available: int, currency: str) -> str:
    status = "🟢 активен" if product["is_active"] else "🔴 скрыт"
    return (
        f"📦 <b>{escape(product['title'])}</b> (ID {product['id']})\n"
        f"Статус: {status}\n"
        f"Цена: {price_str(product['price'], currency)}\n"
        f"В наличии: {available} шт."
    )


def cancelled() -> str:
    return "Отменено."


def new_sale_admin(title: str, user_id: int, username: str | None, price: int, currency: str) -> str:
    who = f"@{username}" if username else f"id{user_id}"
    return (
        "🔔 <b>Новая продажа</b>\n"
        f"Товар: {escape(title)}\n"
        f"Покупатель: {escape(who)}\n"
        f"Сумма: {price_str(price, currency)}"
    )


def error_price() -> str:
    return "⚠️ Цена должна быть целым числом больше нуля. Попробуй ещё раз:"
