"""FSM-состояния мастера добавления правила."""

from aiogram.fsm.state import State, StatesGroup


class AddRule(StatesGroup):
    name = State()
    max_price = State()
    min_float = State()
    max_float = State()
    seeds = State()
    stickers = State()
    discount = State()
    autobuy = State()  # выбор кнопками
