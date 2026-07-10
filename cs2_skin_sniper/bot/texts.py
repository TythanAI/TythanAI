"""Все тексты бота. Меняй здесь."""

from __future__ import annotations

from html import escape

from .models import Listing, Rule


def _f(x: float | None) -> str:
    return "—" if x is None else f"{x:.4f}"


# ── Алерты монитора ───────────────────────────────────────────────────
def listing_alert(listing: Listing) -> str:
    lines = [f"🔔 <b>Найден лот</b> · {escape(listing.market)}",
             f"<b>{escape(listing.name)}</b>",
             f"💵 <b>{listing.price:.2f}$</b>"]
    d = listing.discount()
    if listing.ref_price:
        extra = f" (−{int((d or 0) * 100)}%)" if d else ""
        lines.append(f"📉 реф. {listing.ref_price:.2f}${extra}")
    if listing.float_value is not None:
        lines.append(f"🎯 float {_f(listing.float_value)}")
    if listing.paint_seed is not None:
        lines.append(f"🌱 seed {listing.paint_seed}")
    if listing.stickers:
        lines.append("🏷 " + escape(", ".join(listing.stickers)))
    if listing.url:
        lines.append(listing.url)
    return "\n".join(lines)


def dry_run_note(listing: Listing) -> str:
    return f"🧪 <b>[DRY-RUN]</b> купил бы «{escape(listing.name)}» за {listing.price:.2f}$"


def bought_note(listing: Listing, msg: str) -> str:
    return f"✅ <b>Куплено</b>: «{escape(listing.name)}» за {listing.price:.2f}$\n{escape(msg)}"


def buy_failed_note(listing: Listing, msg: str) -> str:
    return f"❌ Не удалось купить «{escape(listing.name)}» ({listing.price:.2f}$): {escape(msg)}"


def skipped_note(listing: Listing, reason: str) -> str:
    return f"⏸ Пропущено «{escape(listing.name)}» ({listing.price:.2f}$) — {escape(reason)}"


# ── Панель управления ─────────────────────────────────────────────────
def start(markets: list[str]) -> str:
    return (
        "🎯 <b>CS2 Sniper</b>\n\n"
        f"Площадки: <b>{', '.join(markets)}</b>\n"
        "Слежу за лотами по твоим правилам и шлю алерты; на DMarket могу "
        "покупать автоматически (с защитой).\n\n"
        "Открой меню ниже 👇"
    )


def status(running: bool, autobuy: bool, dry_run: bool, limits, spent: float,
           rules_count: int, markets: list[str]) -> str:
    return (
        "📊 <b>Статус</b>\n\n"
        f"🔎 Мониторинг: <b>{'вкл' if running else 'выкл'}</b>\n"
        f"🛒 Автопокупка: <b>{'ВКЛ' if autobuy else 'выкл'}</b>\n"
        f"🧪 Dry-run (без реальных трат): <b>{'ВКЛ' if dry_run else 'выкл'}</b>\n"
        f"🏬 Площадки: {', '.join(markets)}\n"
        f"📏 Правил активно: {rules_count}\n\n"
        f"💵 Лимит за предмет: {limits.max_item_price:g}$\n"
        f"📅 Дневной лимит: {limits.daily_limit:g}$ (потрачено сегодня: {spent:.2f}$)\n"
        f"🛡 Защита баланса: не ниже {limits.min_balance:g}$"
    )


def rules_header() -> str:
    return "📏 <b>Правила поиска</b>\n\nНажми на правило, чтобы удалить/переключить."


def rule_line(r: Rule) -> str:
    parts = [f"#{r.id}", f"«{r.name_query}»", f"≤{r.max_price:g}$"]
    if r.min_float is not None or r.max_float is not None:
        parts.append(f"float {_f(r.min_float)}–{_f(r.max_float)}")
    if r.seeds:
        parts.append("seeds:" + ",".join(map(str, r.seeds[:6])))
    if r.stickers:
        parts.append("🏷" + "/".join(r.stickers[:3]))
    if r.min_discount:
        parts.append(f"−{int(r.min_discount*100)}%")
    parts.append("🛒" if r.autobuy else "🔕")
    parts.append("🟢" if r.active else "🔴")
    return " · ".join(parts)


def no_rules() -> str:
    return "Правил пока нет. Добавь первое — кнопка «➕ Добавить правило»."


def balance_line(balances: dict[str, float | None]) -> str:
    lines = ["💰 <b>Баланс</b>"]
    for market, bal in balances.items():
        lines.append(f"• {market}: " + (f"{bal:.2f}$" if bal is not None else "—"))
    if not balances:
        lines.append("Нет площадок с балансом.")
    return "\n".join(lines)


def purchases_header() -> str:
    return "🧾 <b>Последние покупки</b>\n"


def purchase_line(row) -> str:
    icon = {"bought": "✅", "dry_run": "🧪", "failed": "❌", "skipped": "⏸"}.get(row["status"], "•")
    return f"{icon} {escape(row['name'])} — {row['price']:.2f}$ ({row['status']})"


# ── Мастер добавления правила ─────────────────────────────────────────
ADD_NAME = ("➕ <b>Новое правило</b>\n\nШаг 1/7. Введи <b>название или его часть</b> "
            "(напр. <code>Case Hardened</code> или <code>AK-47 | Redline</code>):")
ADD_MAXPRICE = "Шаг 2/7. <b>Максимальная цена</b> за предмет в USD (напр. <code>25</code>):"
ADD_MINFLOAT = "Шаг 3/7. <b>Минимальный float</b> (напр. <code>0</code>) или «-», чтобы пропустить:"
ADD_MAXFLOAT = "Шаг 4/7. <b>Максимальный float</b> (напр. <code>0.07</code> = Factory New) или «-»:"


def add_seeds(hint_seeds: list[int]) -> str:
    hint = f"\nИзвестные редкие сиды для этого скина: <code>{', '.join(map(str, hint_seeds))}</code>" if hint_seeds else ""
    return ("Шаг 5/7. <b>Paint seed</b> редких паттернов через запятую "
            "(напр. <code>661,670</code>) или «-», чтобы любой:" + hint)


ADD_STICKERS = ("Шаг 6/7. <b>Наклейки</b> — ключевые слова через запятую "
                "(напр. <code>Katowice 2014, Holo</code>) или «-»:")
ADD_DISCOUNT = ("Шаг 7/7. <b>Мин. скидка</b> к реф-цене в %, чтобы считать «дёшево» "
                "(напр. <code>15</code>) или «-»:")


def rule_created(rule_id: int) -> str:
    return (f"✅ Правило #{rule_id} создано.\n"
            "Автопокупку для него можно включить кнопкой в списке правил, а глобально — "
            "переключателями в меню (не забудь выключить Dry-run, когда протестируешь).")


def bad_number() -> str:
    return "⚠️ Нужно число. Попробуй ещё раз (или «-» для пропуска):"


def cancelled() -> str:
    return "Отменено."
