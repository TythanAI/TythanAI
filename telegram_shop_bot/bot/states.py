"""FSM-состояния для многошаговых сценариев админки."""

from aiogram.fsm.state import State, StatesGroup


class AddProduct(StatesGroup):
    title = State()
    description = State()
    category = State()
    price = State()


class AddStock(StatesGroup):
    waiting_items = State()  # в data хранится product_id
