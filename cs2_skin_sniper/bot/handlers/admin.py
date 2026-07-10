"""Панель управления снайпером (только админы)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..config import Config
from ..database import Database
from ..filters import IsAdmin
from ..keyboards import MenuCB, RuleCB, WizCB
from ..models import Rule
from ..patterns import rare_seeds_for
from ..safety import SafetyLimits
from ..states import AddRule
from ..utils import render

router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _num_or_none(text: str) -> float | None:
    text = text.strip().replace(",", ".")
    if text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return "bad"  # маркер ошибки


async def show_menu(event: Message | CallbackQuery, config: Config, db: Database) -> None:
    await render(
        event, texts.start(config.markets),
        kb.main_menu(await db.get_bool("monitoring"), await db.get_bool("autobuy"),
                     await db.get_bool("dry_run")),
    )


async def _limits(db: Database) -> SafetyLimits:
    return SafetyLimits(
        max_item_price=await db.get_float("max_item_price"),
        daily_limit=await db.get_float("daily_limit"),
        min_balance=await db.get_float("min_balance"),
    )


# ── вход / меню / отмена ──────────────────────────────────────────────
@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext, config: Config, db: Database) -> None:
    await state.clear()
    await message.answer(texts.cancelled())
    await show_menu(message, config, db)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, config: Config, db: Database) -> None:
    await state.clear()
    await show_menu(message, config, db)


@router.message(Command("help"))
async def cmd_help(message: Message, config: Config, db: Database) -> None:
    await show_menu(message, config, db)


@router.callback_query(MenuCB.filter(F.action == "home"))
async def cb_home(query: CallbackQuery, state: FSMContext, config: Config, db: Database) -> None:
    await state.clear()
    await show_menu(query, config, db)
    await query.answer()


@router.callback_query(MenuCB.filter(F.action == "status"))
async def cb_status(query: CallbackQuery, config: Config, db: Database) -> None:
    text = texts.status(
        running=await db.get_bool("monitoring"), autobuy=await db.get_bool("autobuy"),
        dry_run=await db.get_bool("dry_run"), limits=await _limits(db),
        spent=await db.spent_today(), rules_count=len(await db.list_rules(only_active=True)),
        markets=config.markets,
    )
    await render(query, text, kb.back_menu())
    await query.answer()


# ── переключатели ─────────────────────────────────────────────────────
@router.callback_query(MenuCB.filter(F.action.in_({"t_monitor", "t_autobuy", "t_dryrun"})))
async def cb_toggle(query: CallbackQuery, callback_data: MenuCB, config: Config, db: Database) -> None:
    key = {"t_monitor": "monitoring", "t_autobuy": "autobuy", "t_dryrun": "dry_run"}[callback_data.action]
    new = not await db.get_bool(key)
    await db.set_setting(key, "1" if new else "0")
    alert = ""
    if key == "autobuy" and new and not await db.get_bool("dry_run"):
        alert = "⚠️ Автопокупка на РЕАЛЬНЫЕ деньги включена!"
    if key == "dry_run" and not new and await db.get_bool("autobuy"):
        alert = "⚠️ Dry-run выключен — покупки пойдут на реальные деньги!"
    await show_menu(query, config, db)
    await query.answer(alert, show_alert=bool(alert))


# ── правила ───────────────────────────────────────────────────────────
@router.callback_query(MenuCB.filter(F.action == "rules"))
async def cb_rules(query: CallbackQuery, db: Database) -> None:
    rules = await db.list_rules()
    if not rules:
        await render(query, texts.no_rules(), kb.back_menu())
    else:
        lines = [texts.rules_header(), ""] + [texts.rule_line(r) for r in rules]
        await render(query, "\n".join(lines), kb.rules_list(rules))
    await query.answer()


@router.callback_query(RuleCB.filter(F.action == "manage"))
async def cb_rule_manage(query: CallbackQuery, callback_data: RuleCB, db: Database) -> None:
    rule = await db.get_rule(callback_data.rule_id)
    if rule is None:
        await query.answer("Правило не найдено", show_alert=True)
        return
    await render(query, "⚙️ " + texts.rule_line(rule), kb.rule_manage(rule))
    await query.answer()


@router.callback_query(RuleCB.filter(F.action == "toggle"))
async def cb_rule_toggle(query: CallbackQuery, callback_data: RuleCB, db: Database) -> None:
    rule = await db.get_rule(callback_data.rule_id)
    if rule is None:
        await query.answer("Не найдено", show_alert=True)
        return
    await db.set_rule_active(rule.id, not rule.active)
    rule = await db.get_rule(rule.id)
    await render(query, "⚙️ " + texts.rule_line(rule), kb.rule_manage(rule))
    await query.answer("Готово")


@router.callback_query(RuleCB.filter(F.action == "autobuy"))
async def cb_rule_autobuy(query: CallbackQuery, callback_data: RuleCB, db: Database) -> None:
    rule = await db.get_rule(callback_data.rule_id)
    if rule is None:
        await query.answer("Не найдено", show_alert=True)
        return
    await db.conn.execute("UPDATE rules SET autobuy = ? WHERE id = ?",
                          (0 if rule.autobuy else 1, rule.id))
    await db.conn.commit()
    rule = await db.get_rule(rule.id)
    await render(query, "⚙️ " + texts.rule_line(rule), kb.rule_manage(rule))
    await query.answer("Готово")


@router.callback_query(RuleCB.filter(F.action == "delete"))
async def cb_rule_delete(query: CallbackQuery, callback_data: RuleCB, db: Database) -> None:
    await db.delete_rule(callback_data.rule_id)
    rules = await db.list_rules()
    if not rules:
        await render(query, texts.no_rules(), kb.back_menu())
    else:
        lines = [texts.rules_header(), ""] + [texts.rule_line(r) for r in rules]
        await render(query, "\n".join(lines), kb.rules_list(rules))
    await query.answer("Удалено")


# ── баланс / покупки ──────────────────────────────────────────────────
@router.callback_query(MenuCB.filter(F.action == "balance"))
async def cb_balance(query: CallbackQuery, db: Database, markets: list) -> None:
    balances: dict[str, float | None] = {}
    for m in markets:
        try:
            balances[m.name] = await m.get_balance()
        except Exception:  # noqa: BLE001
            balances[m.name] = None
    await render(query, texts.balance_line(balances), kb.back_menu())
    await query.answer()


@router.callback_query(MenuCB.filter(F.action == "purchases"))
async def cb_purchases(query: CallbackQuery, db: Database) -> None:
    rows = await db.recent_purchases()
    if not rows:
        await render(query, "🧾 Покупок пока нет.", kb.back_menu())
    else:
        lines = [texts.purchases_header()] + [texts.purchase_line(r) for r in rows]
        await render(query, "\n".join(lines), kb.back_menu())
    await query.answer()


# ── мастер добавления правила ─────────────────────────────────────────
@router.callback_query(MenuCB.filter(F.action == "add_rule"))
async def cb_add_rule(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddRule.name)
    if query.message:
        await query.message.answer(texts.ADD_NAME)
    await query.answer()


@router.message(AddRule.name)
async def w_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Пусто. Введи название или его часть:")
        return
    await state.update_data(name=name)
    await state.set_state(AddRule.max_price)
    await message.answer(texts.ADD_MAXPRICE)


@router.message(AddRule.max_price)
async def w_maxprice(message: Message, state: FSMContext) -> None:
    val = _num_or_none(message.text or "")
    if val is None or val == "bad" or val <= 0:
        await message.answer(texts.bad_number())
        return
    await state.update_data(max_price=val)
    await state.set_state(AddRule.min_float)
    await message.answer(texts.ADD_MINFLOAT)


@router.message(AddRule.min_float)
async def w_minfloat(message: Message, state: FSMContext) -> None:
    val = _num_or_none(message.text or "")
    if val == "bad":
        await message.answer(texts.bad_number())
        return
    await state.update_data(min_float=val)
    await state.set_state(AddRule.max_float)
    await message.answer(texts.ADD_MAXFLOAT)


@router.message(AddRule.max_float)
async def w_maxfloat(message: Message, state: FSMContext) -> None:
    val = _num_or_none(message.text or "")
    if val == "bad":
        await message.answer(texts.bad_number())
        return
    await state.update_data(max_float=val)
    data = await state.get_data()
    await state.set_state(AddRule.seeds)
    await message.answer(texts.add_seeds(rare_seeds_for(data.get("name", ""))))


@router.message(AddRule.seeds)
async def w_seeds(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    seeds: list[int] = []
    if raw != "-":
        seeds = [int(p) for p in raw.replace(" ", "").split(",") if p.lstrip("-").isdigit()]
    await state.update_data(seeds=seeds)
    await state.set_state(AddRule.stickers)
    await message.answer(texts.ADD_STICKERS)


@router.message(AddRule.stickers)
async def w_stickers(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    stickers: list[str] = []
    if raw != "-":
        stickers = [s.strip() for s in raw.split(",") if s.strip()]
    await state.update_data(stickers=stickers)
    await state.set_state(AddRule.discount)
    await message.answer(texts.ADD_DISCOUNT)


@router.message(AddRule.discount)
async def w_discount(message: Message, state: FSMContext) -> None:
    val = _num_or_none(message.text or "")
    if val == "bad":
        await message.answer(texts.bad_number())
        return
    await state.update_data(discount=(val / 100 if val else 0.0))
    await state.set_state(AddRule.autobuy)
    await message.answer("Покупать такие лоты автоматически?", reply_markup=kb.wizard_autobuy())


@router.callback_query(WizCB.filter(), AddRule.autobuy)
async def w_autobuy(query: CallbackQuery, callback_data: WizCB, state: FSMContext,
                    config: Config, db: Database) -> None:
    data = await state.get_data()
    rule = Rule(
        id=0, name_query=data["name"], max_price=data["max_price"],
        min_float=data.get("min_float"), max_float=data.get("max_float"),
        seeds=data.get("seeds", []), stickers=data.get("stickers", []),
        min_discount=data.get("discount", 0.0),
        autobuy=(callback_data.action == "autobuy_yes"), active=True,
    )
    rule_id = await db.add_rule(rule)
    await state.clear()
    if query.message:
        menu = kb.main_menu(await db.get_bool("monitoring"), await db.get_bool("autobuy"),
                            await db.get_bool("dry_run"))
        await query.message.edit_text(texts.rule_created(rule_id), reply_markup=menu)
    await query.answer("Правило создано")
