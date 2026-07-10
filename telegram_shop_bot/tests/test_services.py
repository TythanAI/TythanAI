"""Тесты сервисов: расчёт суммы TON, матчинг оплаты, разбор ответа toncenter,
резерв TON-заказа и снимок базы для бэкапа."""

from __future__ import annotations

import sys
from pathlib import Path

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.database import Database  # noqa: E402
from bot.services.backup import make_snapshot  # noqa: E402
from bot.services.ton import TonClient, format_ton, match_payment, ton_nano_for  # noqa: E402


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db", currency="RUB")
    await database.connect()
    yield database
    await database.close()


# ── расчёт суммы TON ──────────────────────────────────────────────────
def test_ton_nano_for():
    assert ton_nano_for(500, 500) == 1_000_000_000       # 500₽ при 1 TON=500₽ → 1 TON
    assert ton_nano_for(750, 500) == 1_500_000_000       # → 1.5 TON
    assert ton_nano_for(1, 1_000_000) >= 1               # не ноль


def test_format_ton():
    assert format_ton(1_000_000_000) == "1"
    assert format_ton(1_500_000_000) == "1.5"
    assert format_ton(1_230_000_000) == "1.23"


# ── матчинг входящего перевода ────────────────────────────────────────
def test_match_payment():
    txs = [
        {"comment": "abc123", "value_nano": 1_500_000_000, "source": "EQx"},
        {"comment": "other", "value_nano": 9_000_000_000, "source": "EQy"},
    ]
    # верный memo и достаточная сумма
    assert match_payment(txs, "abc123", 1_500_000_000) is not None
    # верный memo, но мало заплатили
    assert match_payment(txs, "abc123", 2_000_000_000) is None
    # нет такого memo
    assert match_payment(txs, "nope", 1) is None


def test_toncenter_parse():
    data = {
        "ok": True,
        "result": [
            {
                "utime": 1700000000,
                "transaction_id": {"hash": "h1"},
                "in_msg": {"source": "EQSender", "destination": "EQShop",
                           "value": "1500000000", "message": "memo42"},
            },
            {   # без source — не пользовательский платёж, пропускаем
                "utime": 1700000001,
                "transaction_id": {"hash": "h2"},
                "in_msg": {"source": "", "value": "100", "message": "x"},
            },
        ],
    }
    parsed = TonClient.parse(data)
    assert len(parsed) == 1
    assert parsed[0]["comment"] == "memo42"
    assert parsed[0]["value_nano"] == 1_500_000_000
    assert parsed[0]["source"] == "EQSender"


# ── резерв TON-заказа ─────────────────────────────────────────────────
async def test_reserve_ton_order(db):
    pid = await db.add_product("acc", "", None, 500)
    await db.add_stock(pid, ["x"])
    product = await db.get_product(pid)
    reserved = await db.reserve_one(product, 5, 500, 500, "ton", None,
                                    memo="abc123", ton_nano=1_000_000_000)
    assert reserved is not None
    assert await db.available_count(pid) == 0
    pending = await db.list_pending_ton_orders()
    assert len(pending) == 1
    assert pending[0]["memo"] == "abc123"
    assert pending[0]["ton_nano"] == 1_000_000_000
    assert pending[0]["method"] == "ton"


# ── снимок базы (бэкап) ───────────────────────────────────────────────
async def test_make_snapshot_is_valid_copy(db, tmp_path):
    pid = await db.add_product("Товар", "", None, 100)
    await db.add_stock(pid, ["a", "b"])
    snap = await make_snapshot(db)
    try:
        assert snap.exists() and snap.stat().st_size > 0
        conn = await aiosqlite.connect(snap)
        cur = await conn.execute("SELECT COUNT(*) FROM products")
        assert (await cur.fetchone())[0] == 1
        cur = await conn.execute("SELECT COUNT(*) FROM stock")
        assert (await cur.fetchone())[0] == 2
        await conn.close()
    finally:
        snap.unlink(missing_ok=True)
