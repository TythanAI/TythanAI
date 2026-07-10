"""Inline-клавиатуры и callback-data."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .models import Rule


class MenuCB(CallbackData, prefix="m"):
    action: str  # home, status, rules, add_rule, balance, purchases, t_monitor, t_autobuy, t_dryrun


class RuleCB(CallbackData, prefix="r"):
    action: str  # manage, toggle, autobuy, delete
    rule_id: int


class WizCB(CallbackData, prefix="w"):
    action: str  # autobuy_yes, autobuy_no


def _onoff(v: bool) -> str:
    return "🟢" if v else "🔴"


def main_menu(monitoring: bool, autobuy: bool, dry_run: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статус", callback_data=MenuCB(action="status"))
    kb.button(text="📏 Правила", callback_data=MenuCB(action="rules"))
    kb.button(text="➕ Добавить правило", callback_data=MenuCB(action="add_rule"))
    kb.button(text="💰 Баланс", callback_data=MenuCB(action="balance"))
    kb.button(text="🧾 Покупки", callback_data=MenuCB(action="purchases"))
    kb.button(text=f"{_onoff(monitoring)} Монитор", callback_data=MenuCB(action="t_monitor"))
    kb.button(text=f"{_onoff(autobuy)} Автобай", callback_data=MenuCB(action="t_autobuy"))
    kb.button(text=f"{_onoff(dry_run)} Dry-run", callback_data=MenuCB(action="t_dryrun"))
    kb.adjust(1, 2, 2, 3)
    return kb.as_markup()


def back_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В меню", callback_data=MenuCB(action="home"))
    return kb.as_markup()


def rules_list(rules: list[Rule]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for r in rules:
        flag = "🟢" if r.active else "🔴"
        buy = "🛒" if r.autobuy else "🔕"
        kb.button(text=f"{flag}{buy} #{r.id} {r.name_query} ≤{r.max_price:g}$",
                  callback_data=RuleCB(action="manage", rule_id=r.id))
    kb.button(text="➕ Добавить правило", callback_data=MenuCB(action="add_rule"))
    kb.button(text="⬅️ В меню", callback_data=MenuCB(action="home"))
    kb.adjust(1)
    return kb.as_markup()


def rule_manage(rule: Rule) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=("🔴 Выключить" if rule.active else "🟢 Включить"),
              callback_data=RuleCB(action="toggle", rule_id=rule.id))
    kb.button(text=("🔕 Автобай выкл" if rule.autobuy else "🛒 Автобай вкл"),
              callback_data=RuleCB(action="autobuy", rule_id=rule.id))
    kb.button(text="🗑 Удалить", callback_data=RuleCB(action="delete", rule_id=rule.id))
    kb.button(text="⬅️ К правилам", callback_data=MenuCB(action="rules"))
    kb.adjust(1)
    return kb.as_markup()


def wizard_autobuy() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Да, покупать автоматически", callback_data=WizCB(action="autobuy_yes"))
    kb.button(text="🔕 Нет, только алерт", callback_data=WizCB(action="autobuy_no"))
    kb.adjust(1)
    return kb.as_markup()
