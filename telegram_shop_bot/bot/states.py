"""FSM-состояния для многошаговых сценариев."""

from aiogram.fsm.state import State, StatesGroup


class AddProduct(StatesGroup):
    title = State()
    description = State()
    price = State()
    category = State()  # выбор категории кнопками (не текст)


class AddStock(StatesGroup):
    waiting_items = State()  # data: product_id


class AddCategory(StatesGroup):
    name = State()  # data: parent_id (или None)


class AddPromo(StatesGroup):
    code = State()
    discount = State()   # data: code
    limit = State()      # data: code, discount_type, discount_value


class Broadcast(StatesGroup):
    message = State()
    confirm = State()    # data: text


class EnterPromo(StatesGroup):
    code = State()       # покупатель вводит промокод


class LeaveReview(StatesGroup):
    rating = State()     # data: product_id
    text = State()       # data: product_id, rating
