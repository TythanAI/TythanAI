"""Все тексты, которые видит пользователь. Меняй их здесь — код трогать не нужно."""

from __future__ import annotations

from html import escape

from .config import currency_symbol  # re-export

__all__ = ["currency_symbol"]


def price_str(amount: int, currency: str) -> str:
    return f"{amount} {currency_symbol(currency)}"


def rating_str(avg: float, count: int) -> str:
    if count == 0:
        return "отзывов пока нет"
    return f"⭐️ {avg:.1f} ({count})"


# ── Меню / общее ──────────────────────────────────────────────────────
def welcome(shop_name: str) -> str:
    return (
        f"👋 Добро пожаловать в <b>{escape(shop_name)}</b>!\n\n"
        "Товары выдаются автоматически — оплата и выдача проходят прямо в боте.\n\n"
        "Выбери действие 👇"
    )


def catalog_empty() -> str:
    return "🛒 Каталог пока пуст. Загляни позже!"


def catalog_header(path: str | None) -> str:
    if path:
        return f"🛍 <b>Каталог</b> › {escape(path)}\n\nВыбери категорию или товар:"
    return "🛍 <b>Каталог</b>\n\nВыбери категорию или товар:"


def product_card(product, available: int, currency: str, avg: float, cnt: int,
                 cat_path: str | None, promo=None) -> str:
    title = escape(product["title"])
    desc = escape(product["description"]) if product["description"] else "—"
    lines = [f"📦 <b>{title}</b>", ""]
    if cat_path:
        lines.append(f"🏷 {escape(cat_path)}")
    lines.append(f"⭐️ Рейтинг: {rating_str(avg, cnt)}")
    if promo is not None:
        from .utils import apply_discount, promo_label
        new_price = apply_discount(product["price"], promo)
        lines.append(
            f"💵 Цена: <s>{price_str(product['price'], currency)}</s> → "
            f"<b>{price_str(new_price, currency)}</b>  (промокод {escape(promo['code'])} {promo_label(promo)})"
        )
    else:
        lines.append(f"💵 Цена: <b>{price_str(product['price'], currency)}</b>")
    lines.append(f"{'✅ В наличии: <b>' + str(available) + '</b> шт.' if available > 0 else '⛔️ Нет в наличии'}")
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
        "Оплата <b>полностью возвращена</b> автоматически. Приносим извинения!"
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


# ── Промокоды (покупатель) ────────────────────────────────────────────
def promo_prompt(active: str | None) -> str:
    base = "🎟 <b>Промокод</b>\n\nОтправь код одним сообщением."
    if active:
        base += f"\n\nСейчас применён: <b>{escape(active)}</b>"
    return base


def promo_applied(code: str, label: str) -> str:
    return f"✅ Промокод <b>{escape(code)}</b> ({label}) применён! Скидка учтётся при покупке."


def promo_invalid() -> str:
    return "❌ Такого промокода нет, он недействителен или закончился. Попробуй другой."


# ── Отзывы ────────────────────────────────────────────────────────────
def reviews_empty() -> str:
    return "⭐️ Отзывов пока нет. Стань первым после покупки!"


def reviews_header(title: str | None) -> str:
    if title:
        return f"⭐️ <b>Отзывы: {escape(title)}</b>\n"
    return "⭐️ <b>Последние отзывы</b>\n"


def review_line(r, with_product: bool) -> str:
    stars = "⭐️" * int(r["rating"])
    who = "покупатель"
    head = f"{stars}"
    if with_product and r["product_title"]:
        head += f" · {escape(r['product_title'])}"
    body = f"\n{escape(r['text'])}" if r["text"] else ""
    return f"{head} — {who}{body}"


def review_need_purchase() -> str:
    return "✍️ Оставить отзыв можно только после покупки этого товара."


def review_ask_rating() -> str:
    return "✍️ <b>Оставить отзыв</b>\n\nПоставь оценку:"


def review_ask_text() -> str:
    return "Напиши текст отзыва одним сообщением (или отправь «-», чтобы без текста):"


def review_thanks() -> str:
    return "🙏 Спасибо за отзыв!"


# ── Выбор способа оплаты ──────────────────────────────────────────────
def method_label(method: str) -> str:
    return {
        "stars": "⭐️ Telegram Stars",
        "provider": "🏦 Банковская карта",
        "manual": "💳 Перевод на карту",
        "ton": "💎 Криптовалюта TON",
    }.get(method, method)


def choose_payment_method() -> str:
    return "💳 <b>Способ оплаты</b>\n\nВыбери, как удобнее оплатить:"


# ── Оплата в TON ──────────────────────────────────────────────────────
def ton_invoice(title: str, ton_str: str, wallet: str, memo: str,
                order_id: int, price: int, currency: str) -> str:
    return (
        f"💎 <b>Оплата в TON · заказ #{order_id}</b>\n"
        f"Товар: <b>{escape(title)}</b>\n"
        f"Цена: {price_str(price, currency)}\n\n"
        f"1️⃣ Переведи <b>ровно {ton_str} TON</b> на кошелёк:\n"
        f"<code>{escape(wallet)}</code>\n\n"
        f"2️⃣ ОБЯЗАТЕЛЬНО укажи комментарий (memo) к переводу:\n"
        f"<code>{escape(memo)}</code>\n\n"
        "❗️ Без этого комментария платёж не засчитается. Товар зарезервирован за тобой.\n"
        "3️⃣ После перевода нажми «🔄 Я оплатил — проверить» (обычно 10–40 секунд)."
    )


def ton_not_found() -> str:
    return (
        "⏳ Оплата пока не найдена.\n"
        "Если только что перевёл — подожди 20–40 секунд и нажми ещё раз. "
        "Убедись, что указал комментарий и точную сумму."
    )


# ── Бэкапы (админ) ────────────────────────────────────────────────────
def backup_ok(to_self: bool) -> str:
    return "✅ Бэкап отправлен тебе в этот чат." if to_self else "✅ Бэкап отправлен в чат бэкапов."


def backup_failed() -> str:
    return "⚠️ Не удалось сделать бэкап. Проверь логи и права бота в чате бэкапов."


# ── Ручная оплата ─────────────────────────────────────────────────────
def manual_invoice(title: str, price: int, currency: str, details: str, order_id: int) -> str:
    return (
        f"🧾 <b>Заказ #{order_id}</b>\n"
        f"Товар: <b>{escape(title)}</b>\n"
        f"К оплате: <b>{price_str(price, currency)}</b>\n\n"
        f"💳 Реквизиты для оплаты:\n{escape(details)}\n\n"
        "После оплаты нажми «✅ Я оплатил(а)» — админ проверит и бот выдаст товар.\n"
        "⏳ Товар зарезервирован за тобой."
    )


def manual_awaiting() -> str:
    return "⏳ Спасибо! Заявка отправлена админу на проверку. Как подтвердят — товар придёт сюда."


def manual_cancelled() -> str:
    return "❌ Заказ отменён, резерв снят."


def manual_rejected() -> str:
    return "❌ Оплата не подтверждена админом. Если это ошибка — напиши в поддержку."


def admin_manual_request(order_id: int, title: str, price: int, currency: str,
                         user_id: int, username: str | None) -> str:
    who = f"@{username}" if username else f"id{user_id}"
    return (
        f"🔔 <b>Новая заявка на оплату</b>\n"
        f"Заказ #{order_id}\n"
        f"Товар: {escape(title)}\n"
        f"Сумма: {price_str(price, currency)}\n"
        f"Покупатель: {escape(who)}\n\n"
        "Проверь поступление оплаты и подтверди либо отклони:"
    )


# ── Уведомления о продаже ─────────────────────────────────────────────
def new_sale_admin(title: str, user_id: int, username: str | None, price: int, currency: str) -> str:
    who = f"@{username}" if username else f"id{user_id}"
    return (
        "🔔 <b>Новая продажа</b>\n"
        f"Товар: {escape(title)}\n"
        f"Покупатель: {escape(who)}\n"
        f"Сумма: {price_str(price, currency)}"
    )


# ── Админка: общее ────────────────────────────────────────────────────
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


def cancelled() -> str:
    return "Отменено."


def error_price() -> str:
    return "⚠️ Цена должна быть целым числом больше нуля. Попробуй ещё раз:"


# ── Админка: товары ───────────────────────────────────────────────────
ADD_PRODUCT_TITLE = "➕ <b>Новый товар</b>\n\nШаг 1/4. Введи <b>название</b> товара:"
ADD_PRODUCT_DESC = "Шаг 2/4. Введи <b>описание</b> (или «-», чтобы пропустить):"


def add_product_price(currency: str) -> str:
    unit = "звёздах (целое число, минимум 1)" if currency.upper() == "XTR" else f"{currency}"
    return f"Шаг 3/4. Введи <b>цену</b> в {unit}:"


def add_product_category() -> str:
    return "Шаг 4/4. Выбери <b>категорию</b> товара:"


def product_created(product_id: int, title: str) -> str:
    return (
        f"✅ Товар создан: <b>{escape(title)}</b> (ID {product_id}).\n\n"
        "Теперь добавь «наличие» — кнопка «📦 Добавить наличие»."
    )


def choose_product_for_stock() -> str:
    return "📦 <b>Добавить наличие</b>\n\nВыбери товар:"


def ask_stock_items(title: str) -> str:
    return (
        f"📦 Товар: <b>{escape(title)}</b>\n\n"
        "Пришли единицы наличия — <b>по одной на строку</b>. Например:\n"
        "<code>login1:pass1\nlogin2:pass2\nlogin3:pass3</code>\n\n"
        "Каждая строка станет отдельным товаром для выдачи. Отправь /cancel для отмены."
    )


def stock_added(count: int, title: str) -> str:
    return f"✅ Добавлено единиц наличия: <b>{count}</b> в товар «{escape(title)}»."


def no_products_yet() -> str:
    return "Товаров пока нет. Сначала создай товар кнопкой «➕ Добавить товар»."


def admin_products_header() -> str:
    return "📋 <b>Товары</b>\n\nНажми на товар, чтобы управлять им:"


def admin_product_manage(product, available: int, currency: str, cat_path: str | None) -> str:
    status = "🟢 активен" if product["is_active"] else "🔴 скрыт"
    cat = escape(cat_path) if cat_path else "без категории"
    return (
        f"📦 <b>{escape(product['title'])}</b> (ID {product['id']})\n"
        f"Статус: {status}\n"
        f"Категория: {cat}\n"
        f"Цена: {price_str(product['price'], currency)}\n"
        f"В наличии: {available} шт."
    )


# ── Админка: категории ────────────────────────────────────────────────
def admin_cats_header(path: str | None) -> str:
    where = f" › {escape(path)}" if path else ""
    return (
        f"🗂 <b>Категории</b>{where}\n\n"
        "Заходи в категорию, чтобы создать подкатегории, "
        "или добавь новую здесь."
    )


def ask_category_name() -> str:
    return "Введи <b>название</b> категории:"


def category_added(name: str) -> str:
    return f"✅ Категория «{escape(name)}» создана."


def category_deleted() -> str:
    return "🗑 Категория удалена (товары из неё стали «без категории»)."


# ── Админка: промокоды ────────────────────────────────────────────────
def promos_header() -> str:
    return "🎟 <b>Промокоды</b>\n\nНажми на код, чтобы удалить его."


def promo_line(p) -> str:
    typ = f"{p['discount_value']}%" if p["discount_type"] == "percent" else f"{p['discount_value']} фикс."
    limit = "∞" if not p["max_uses"] else f"{p['used_count']}/{p['max_uses']}"
    status = "" if p["is_active"] else " (выкл)"
    return f"<code>{escape(p['code'])}</code> — {typ}, использований: {limit}{status}"


def ask_promo_code() -> str:
    return (
        "🎟 <b>Новый промокод</b>\n\n"
        "Шаг 1/3. Введи <b>код</b> (латиница/цифры, например SALE10):"
    )


def ask_promo_discount() -> str:
    return (
        "Шаг 2/3. Введи размер скидки:\n"
        "• <code>10%</code> — процент от цены\n"
        "• <code>50</code> — фиксированная сумма"
    )


def ask_promo_limit() -> str:
    return "Шаг 3/3. Сколько раз можно использовать? Введи число или <code>0</code> — без лимита:"


def promo_created(code: str) -> str:
    return f"✅ Промокод <b>{escape(code)}</b> создан."


def promo_code_exists() -> str:
    return "⚠️ Такой код уже есть. Введи другой:"


def promo_bad_discount() -> str:
    return "⚠️ Не понял. Введи, например, <code>10%</code> или <code>50</code>:"


def promo_deleted(code: str) -> str:
    return f"🗑 Промокод {escape(code)} удалён."


# ── Админка: рассылка ─────────────────────────────────────────────────
def broadcast_ask() -> str:
    return (
        "📣 <b>Рассылка</b>\n\n"
        "Пришли сообщение (текст), которое отправить всем пользователям бота.\n"
        "Отправь /cancel для отмены."
    )


def broadcast_preview(text: str, count: int) -> str:
    return (
        "📣 <b>Проверь рассылку</b>\n\n"
        f"Получателей: <b>{count}</b>\n\n"
        "———\n"
        f"{escape(text)}\n"
        "———\n\n"
        "Отправляем?"
    )


def broadcast_done(ok: int, failed: int) -> str:
    return f"✅ Рассылка завершена.\nДоставлено: <b>{ok}</b>\nНе доставлено: <b>{failed}</b>"


def broadcast_empty() -> str:
    return "⚠️ Пусто. Пришли текст сообщения или /cancel."


# ── Админка: отзывы ───────────────────────────────────────────────────
def admin_reviews_header() -> str:
    return "⭐️ <b>Последние отзывы</b>\n"
