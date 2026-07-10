"""Пользовательские обработчики: меню, каталог, промокоды, покупки, отзывы."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..config import Config
from ..database import Database
from ..keyboards import CatCB, MenuCB, ProductCB, RateCB
from ..states import EnterPromo, LeaveReview
from ..utils import active_promo, apply_discount, promo_label, render

router = Router(name="user")


async def show_menu(event: Message | CallbackQuery, config: Config, state: FSMContext) -> None:
    await state.set_state(None)
    is_admin = config.is_admin(event.from_user.id if event.from_user else None)
    await render(
        event,
        texts.welcome(config.shop_name),
        kb.main_menu(is_admin=is_admin, has_support=bool(config.support_contact)),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, config: Config, state: FSMContext) -> None:
    user = message.from_user
    if user:
        await db.upsert_user(user.id, user.username, user.first_name)
    await show_menu(message, config, state)


@router.message(Command("help"))
async def cmd_help(message: Message, config: Config, state: FSMContext) -> None:
    await show_menu(message, config, state)


@router.callback_query(MenuCB.filter(F.action == "home"))
async def cb_home(query: CallbackQuery, config: Config, state: FSMContext) -> None:
    await show_menu(query, config, state)
    await query.answer()


# ── Каталог с категориями ─────────────────────────────────────────────
@router.callback_query(CatCB.filter())
async def cb_catalog(query: CallbackQuery, callback_data: CatCB, db: Database,
                     config: Config, state: FSMContext) -> None:
    await state.set_state(None)
    cat_id = callback_data.cat_id
    is_root = cat_id == 0
    parent = None if is_root else cat_id
    subcats = await db.list_categories(parent_id=parent)
    products = await db.list_products_in_category(None if is_root else cat_id, only_active=True)

    if not subcats and not products:
        if is_root:
            await render(query, texts.catalog_empty(), kb.back_to_menu())
            await query.answer()
            return

    back_cat = 0
    if not is_root:
        row = await db.get_category(cat_id)
        back_cat = (row["parent_id"] or 0) if row else 0
    path = await db.category_path(cat_id) if not is_root else None
    await render(
        query,
        texts.catalog_header(path),
        kb.catalog_screen(subcats, products, cat_id, back_cat, is_root, config.currency),
    )
    await query.answer()


@router.callback_query(ProductCB.filter(F.action == "view"))
async def cb_view_product(query: CallbackQuery, callback_data: ProductCB, db: Database,
                          config: Config, state: FSMContext) -> None:
    product = await db.get_product(callback_data.product_id)
    if product is None or not product["is_active"]:
        await query.answer("Товар недоступен", show_alert=True)
        return
    available = await db.available_count(product["id"])
    avg, cnt = await db.product_rating(product["id"])
    cat_path = await db.category_path(product["category_id"])
    promo = await active_promo(state, db)
    price = apply_discount(product["price"], promo)
    price_label = texts.price_str(price, config.currency)
    can_review = False
    if query.from_user:
        can_review = await db.has_purchased(query.from_user.id, product["id"])
    await render(
        query,
        texts.product_card(product, available, config.currency, avg, cnt, cat_path or None, promo),
        kb.product_view(product["id"], available, price_label, callback_data.back, cnt > 0, can_review),
    )
    await query.answer()


# ── Промокод ──────────────────────────────────────────────────────────
@router.callback_query(MenuCB.filter(F.action == "promo"))
async def cb_promo(query: CallbackQuery, state: FSMContext, db: Database) -> None:
    promo = await active_promo(state, db)
    await state.set_state(EnterPromo.code)
    if query.message:
        await query.message.answer(texts.promo_prompt(promo["code"] if promo else None))
    await query.answer()


@router.message(EnterPromo.code)
async def on_promo_code(message: Message, state: FSMContext, db: Database, config: Config) -> None:
    code = (message.text or "").strip().upper()
    promo = await db.valid_promocode(code)
    if promo is None:
        await message.answer(texts.promo_invalid())
        return
    await state.set_state(None)
    await state.update_data(promo_code=code)
    await message.answer(
        texts.promo_applied(code, promo_label(promo)),
        reply_markup=kb.main_menu(config.is_admin(message.from_user.id), bool(config.support_contact)),
    )


# ── Покупки / поддержка ───────────────────────────────────────────────
@router.callback_query(MenuCB.filter(F.action == "purchases"))
async def cb_purchases(query: CallbackQuery, db: Database, config: Config) -> None:
    if query.from_user is None:
        return
    orders = await db.get_user_orders(query.from_user.id)
    if not orders:
        await render(query, texts.purchases_empty(), kb.back_to_menu())
    else:
        lines = [texts.purchases_header()]
        lines += [texts.purchase_line(o, config.currency) for o in orders]
        await render(query, "\n".join(lines), kb.back_to_menu())
    await query.answer()


@router.callback_query(MenuCB.filter(F.action == "support"))
async def cb_support(query: CallbackQuery, config: Config) -> None:
    await render(query, texts.support(config.support_contact), kb.back_to_menu())
    await query.answer()


# ── Отзывы ────────────────────────────────────────────────────────────
@router.callback_query(MenuCB.filter(F.action == "reviews"))
async def cb_reviews(query: CallbackQuery, db: Database) -> None:
    reviews = await db.list_recent_reviews()
    if not reviews:
        await render(query, texts.reviews_empty(), kb.back_to_menu())
    else:
        lines = [texts.reviews_header(None)]
        lines += [texts.review_line(r, with_product=True) for r in reviews]
        await render(query, "\n\n".join(lines), kb.back_to_menu())
    await query.answer()


@router.callback_query(ProductCB.filter(F.action == "reviews"))
async def cb_product_reviews(query: CallbackQuery, callback_data: ProductCB, db: Database) -> None:
    product = await db.get_product(callback_data.product_id)
    reviews = await db.list_product_reviews(callback_data.product_id)
    title = product["title"] if product else None
    if not reviews:
        await render(query, texts.reviews_empty(), kb.back_to_menu())
    else:
        lines = [texts.reviews_header(title)]
        lines += [texts.review_line(r, with_product=False) for r in reviews]
        await render(query, "\n\n".join(lines), kb.back_to_menu())
    await query.answer()


@router.callback_query(ProductCB.filter(F.action == "review"))
async def cb_leave_review(query: CallbackQuery, callback_data: ProductCB, db: Database,
                          state: FSMContext) -> None:
    if query.from_user is None:
        return
    if not await db.has_purchased(query.from_user.id, callback_data.product_id):
        await query.answer(texts.review_need_purchase(), show_alert=True)
        return
    await state.set_state(LeaveReview.rating)
    await state.update_data(review_product_id=callback_data.product_id)
    if query.message:
        await query.message.answer(texts.review_ask_rating(), reply_markup=kb.rating_kb(callback_data.product_id))
    await query.answer()


@router.callback_query(RateCB.filter(), LeaveReview.rating)
async def cb_rate(query: CallbackQuery, callback_data: RateCB, state: FSMContext) -> None:
    await state.update_data(review_rating=callback_data.rating, review_product_id=callback_data.product_id)
    await state.set_state(LeaveReview.text)
    if query.message:
        await query.message.answer(texts.review_ask_text())
    await query.answer()


@router.message(LeaveReview.text)
async def on_review_text(message: Message, state: FSMContext, db: Database, config: Config) -> None:
    data = await state.get_data()
    product_id = data.get("review_product_id")
    rating = data.get("review_rating")
    if not product_id or not rating:
        await state.set_state(None)
        return
    text = (message.text or "").strip()
    text = "" if text == "-" else text
    await db.add_review(message.from_user.id, int(product_id), int(rating), text)
    await state.set_state(None)
    await message.answer(
        texts.review_thanks(),
        reply_markup=kb.main_menu(config.is_admin(message.from_user.id), bool(config.support_contact)),
    )


@router.message()
async def fallback(message: Message, config: Config, state: FSMContext) -> None:
    """Любое непонятое сообщение — показываем меню. Роутер user подключается
    последним, поэтому команды, шаги админки и оплата уже обработаны."""
    await show_menu(message, config, state)
