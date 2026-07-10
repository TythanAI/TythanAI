"""Тесты слоя данных: каталог, наличие, атомарная выдача, статистика.

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


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db", currency="XTR")
    await database.connect()
    yield database
    await database.close()


async def test_add_product_and_list(db):
    pid = await db.add_product("Аккаунт", "описание", "Категория", 50)
    products = await db.list_products(only_active=True)
    assert len(products) == 1
    assert products[0]["id"] == pid
    assert products[0]["available"] == 0  # наличия ещё нет


async def test_stock_and_available(db):
    pid = await db.add_product("Товар", "", "", 10)
    added = await db.add_stock(pid, ["a:1", "b:2", "  ", "c:3"])
    assert added == 3  # пустые строки не считаются
    assert await db.available_count(pid) == 3


async def test_deliver_marks_sold_and_creates_order(db):
    pid = await db.add_product("Товар", "", "", 10)
    await db.add_stock(pid, ["only-one"])
    product = await db.get_product(pid)

    first = await db.deliver_one(product, user_id=111, charge_id="ch1")
    assert first is not None
    assert first["payload"] == "only-one"
    assert await db.available_count(pid) == 0

    # больше выдавать нечего
    second = await db.deliver_one(product, user_id=222, charge_id="ch2")
    assert second is None

    orders = await db.get_user_orders(111)
    assert len(orders) == 1
    assert orders[0]["payload"] == "only-one"


async def test_no_double_sell_under_concurrency(db):
    """Пять единиц, десять одновременных покупателей — ровно 5 успешных выдач,
    и ни одна единица не выдана дважды."""
    pid = await db.add_product("Товар", "", "", 10)
    await db.add_stock(pid, [f"item-{i}" for i in range(5)])
    product = await db.get_product(pid)

    results = await asyncio.gather(
        *(db.deliver_one(product, user_id=1000 + i, charge_id=f"c{i}") for i in range(10))
    )
    delivered = [r for r in results if r is not None]
    payloads = [r["payload"] for r in delivered]

    assert len(delivered) == 5
    assert len(set(payloads)) == 5  # без дублей
    assert await db.available_count(pid) == 0


async def test_stats(db):
    pid = await db.add_product("Товар", "", "", 25)
    await db.add_stock(pid, ["x", "y"])
    product = await db.get_product(pid)
    await db.upsert_user(1, "user", "User")
    await db.deliver_one(product, user_id=1, charge_id="c1")

    stats = await db.stats()
    assert stats["orders"] == 1
    assert stats["revenue"] == 25
    assert stats["stock"] == 1  # одна единица осталась
    assert stats["users"] == 1


async def test_delete_product_cascades_stock(db):
    pid = await db.add_product("Товар", "", "", 10)
    await db.add_stock(pid, ["a", "b"])
    await db.delete_product(pid)
    assert await db.list_products(only_active=False) == []
    assert await db.available_count(pid) == 0
