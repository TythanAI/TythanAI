"""Тесты слоя данных: каталог, категории, наличие, выдача, ручная оплата,
промокоды, отзывы, статистика.

Запуск:
    cd telegram_shop_bot
    pip install -r requirements.txt pytest pytest-asyncio
    pytest
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.database import Database  # noqa: E402
from bot.utils import apply_discount  # noqa: E402


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db", currency="XTR")
    await database.connect()
    yield database
    await database.close()


# ── товары / наличие ──────────────────────────────────────────────────
async def test_add_product_and_list(db):
    pid = await db.add_product("Аккаунт", "описание", None, 50)
    products = await db.list_all_products(only_active=True)
    assert len(products) == 1
    assert products[0]["id"] == pid
    assert products[0]["available"] == 0


async def test_stock_and_available(db):
    pid = await db.add_product("Товар", "", None, 10)
    added = await db.add_stock(pid, ["a:1", "b:2", "  ", "c:3"])
    assert added == 3
    assert await db.available_count(pid) == 3


async def test_deliver_marks_sold_and_creates_paid_order(db):
    pid = await db.add_product("Товар", "", None, 10)
    await db.add_stock(pid, ["only-one"])
    product = await db.get_product(pid)

    first = await db.deliver_one(product, 111, "ch1", 10, 10, "stars")
    assert first is not None and first["payload"] == "only-one"
    assert await db.available_count(pid) == 0
    assert await db.deliver_one(product, 222, "ch2", 10, 10, "stars") is None

    orders = await db.get_user_orders(111)
    assert len(orders) == 1 and orders[0]["payload"] == "only-one"
    assert await db.has_purchased(111, pid)


async def test_no_double_sell_under_concurrency(db):
    pid = await db.add_product("Товар", "", None, 10)
    await db.add_stock(pid, [f"item-{i}" for i in range(5)])
    product = await db.get_product(pid)

    results = await asyncio.gather(
        *(db.deliver_one(product, 1000 + i, f"c{i}", 10, 10, "stars") for i in range(10))
    )
    delivered = [r for r in results if r is not None]
    payloads = [r["payload"] for r in delivered]
    assert len(delivered) == 5
    assert len(set(payloads)) == 5
    assert await db.available_count(pid) == 0


# ── ручная оплата: резерв / подтверждение / отклонение ────────────────
async def test_manual_reserve_then_approve(db):
    pid = await db.add_product("Товар", "", None, 100)
    await db.add_stock(pid, ["acc-1"])
    product = await db.get_product(pid)

    reserved = await db.reserve_one(product, 7, 90, 100, "manual", "SALE10")
    assert reserved is not None
    assert await db.available_count(pid) == 0  # зарезервировано, недоступно

    result = await db.approve_order(reserved["order_id"])
    assert result is not None and result["payload"] == "acc-1"
    assert result["price"] == 90 and result["promo_code"] == "SALE10"
    orders = await db.get_user_orders(7)
    assert len(orders) == 1
    # повторное подтверждение не срабатывает
    assert await db.approve_order(reserved["order_id"]) is None


async def test_manual_reserve_then_reject_releases_stock(db):
    pid = await db.add_product("Товар", "", None, 100)
    await db.add_stock(pid, ["acc-1"])
    product = await db.get_product(pid)

    reserved = await db.reserve_one(product, 7, 100, 100, "manual")
    assert await db.available_count(pid) == 0
    order = await db.reject_order(reserved["order_id"])
    assert order is not None
    assert await db.available_count(pid) == 1  # вернулось в наличие
    assert await db.get_user_orders(7) == []   # rejected не считается покупкой


async def test_manual_no_oversell_concurrent(db):
    pid = await db.add_product("Товар", "", None, 100)
    await db.add_stock(pid, ["a", "b"])
    product = await db.get_product(pid)
    reservations = await asyncio.gather(
        *(db.reserve_one(product, 10 + i, 100, 100, "manual") for i in range(5))
    )
    assert sum(1 for r in reservations if r is not None) == 2
    assert await db.available_count(pid) == 0


# ── промокоды ─────────────────────────────────────────────────────────
async def test_promocode_percent_and_limit(db):
    await db.add_promocode("SALE10", "percent", 10, max_uses=2)
    promo = await db.valid_promocode("sale10")  # регистр не важен
    assert promo is not None
    assert apply_discount(100, promo) == 90
    await db.use_promocode("SALE10")
    await db.use_promocode("SALE10")
    assert await db.valid_promocode("SALE10") is None  # лимит исчерпан


async def test_promocode_fixed_and_floor(db):
    await db.add_promocode("MINUS200", "fixed", 200)
    promo = await db.valid_promocode("MINUS200")
    assert apply_discount(150, promo) == 1  # не ниже 1


async def test_promocode_expired(db):
    await db.add_promocode("OLD", "fixed", 5, expires_at=1)
    assert await db.valid_promocode("OLD") is None


# ── категории ─────────────────────────────────────────────────────────
async def test_categories_tree_and_path(db):
    root = await db.add_category("Аккаунты", None)
    sub = await db.add_category("Instagram", root)
    assert await db.category_path(sub) == "Аккаунты › Instagram"
    assert len(await db.list_categories(root)) == 1

    await db.add_product("acc", "", sub, 10)
    assert len(await db.list_products_in_category(sub)) == 1
    assert len(await db.list_products_in_category(None)) == 0  # не в «без категории»


async def test_delete_category_sets_products_uncategorized(db):
    root = await db.add_category("Аккаунты", None)
    sub = await db.add_category("Instagram", root)
    pid = await db.add_product("acc", "", sub, 10)
    await db.delete_category(root)  # каскадом удаляет и подкатегорию
    prod = await db.get_product(pid)
    assert prod["category_id"] is None
    assert await db.all_categories() == []


# ── отзывы ────────────────────────────────────────────────────────────
async def test_reviews_and_rating(db):
    pid = await db.add_product("acc", "", None, 10)
    await db.add_review(1, pid, 5, "отлично")
    await db.add_review(2, pid, 3, "нормально")
    avg, cnt = await db.product_rating(pid)
    assert cnt == 2 and 3.9 < avg < 4.1
    assert len(await db.list_product_reviews(pid)) == 2
    assert len(await db.list_recent_reviews()) == 2


# ── статистика ────────────────────────────────────────────────────────
async def test_stats(db):
    pid = await db.add_product("Товар", "", None, 25)
    await db.add_stock(pid, ["x", "y"])
    product = await db.get_product(pid)
    await db.upsert_user(1, "user", "User")
    await db.deliver_one(product, 1, "c1", 25, 25, "stars")

    s = await db.stats()
    assert s["orders"] == 1 and s["revenue"] == 25
    assert s["stock"] == 1 and s["users"] == 1


async def test_migration_from_legacy_is_sold(tmp_path):
    """Старая БД со stock.is_sold должна корректно мигрировать в state."""
    import aiosqlite

    path = tmp_path / "legacy.db"
    conn = await aiosqlite.connect(path)
    await conn.executescript(
        "CREATE TABLE products(id INTEGER PRIMARY KEY, title TEXT, description TEXT, "
        "category TEXT, price INTEGER, is_active INTEGER, created_at INTEGER);"
        "CREATE TABLE stock(id INTEGER PRIMARY KEY, product_id INTEGER, payload TEXT, "
        "is_sold INTEGER DEFAULT 0, order_id INTEGER, created_at INTEGER, sold_at INTEGER);"
        "INSERT INTO products VALUES(1,'t','','',10,1,0);"
        "INSERT INTO stock(id,product_id,payload,is_sold,created_at) VALUES(1,1,'sold',1,0),(2,1,'free',0,0);"
    )
    await conn.commit()
    await conn.close()

    db = Database(path, currency="XTR")
    await db.connect()
    # одна продана (state=2), одна свободна (state=0)
    assert await db.available_count(1) == 1
    await db.close()
