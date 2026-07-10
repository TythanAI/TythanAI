"""Тесты снайпера: правила, защита, mock-маркет, парсеры, монитор end-to-end.

    cd cs2_skin_sniper && pip install -r requirements.txt pytest pytest-asyncio && pytest
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("BOT_TOKEN", "1:x")
os.environ.setdefault("ADMIN_IDS", "111")
os.environ.setdefault("MARKETS", "mock")

from bot.config import Config  # noqa: E402
from bot.database import Database  # noqa: E402
from bot.markets.dmarket import DMarketMarket  # noqa: E402
from bot.markets.mock import MockMarket  # noqa: E402
from bot.markets.steam import SteamMarket  # noqa: E402
from bot.models import Listing, Rule  # noqa: E402
from bot.rules import matches  # noqa: E402
from bot.safety import SafetyLimits, evaluate_buy  # noqa: E402
from bot.services import monitor  # noqa: E402

CONFIG = Config.load()


def rule(**kw) -> Rule:
    base = dict(id=1, name_query="Case Hardened", max_price=100.0, min_float=None,
                max_float=None, seeds=[], stickers=[], min_discount=0.0, autobuy=True, active=True)
    base.update(kw)
    return Rule(**base)


def listing(**kw) -> Listing:
    base = dict(market="mock", listing_id="1", name="AK-47 | Case Hardened (Field-Tested)",
                price=50.0)
    base.update(kw)
    return Listing(**base)


class FakeBot:
    def __init__(self):
        self.msgs: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kw):
        self.msgs.append((chat_id, text))


@pytest.fixture
async def db(tmp_path):
    d = Database(tmp_path / "t.db")
    await d.connect(CONFIG)
    yield d
    await d.close()


# ── правила ───────────────────────────────────────────────────────────
def test_match_basic():
    assert matches(rule(), listing()) is True


def test_match_price_over():
    assert matches(rule(max_price=40), listing(price=50)) is False


def test_match_name_mismatch():
    assert matches(rule(name_query="Redline"), listing()) is False


def test_match_float_range():
    assert matches(rule(max_float=0.07), listing(float_value=0.03)) is True
    assert matches(rule(max_float=0.07), listing(float_value=0.20)) is False
    assert matches(rule(max_float=0.07), listing(float_value=None)) is False  # нет float


def test_match_seeds():
    assert matches(rule(seeds=[661, 670]), listing(paint_seed=661)) is True
    assert matches(rule(seeds=[661, 670]), listing(paint_seed=5)) is False
    assert matches(rule(seeds=[661]), listing(paint_seed=None)) is False


def test_match_stickers():
    r = rule(stickers=["Katowice 2014"])
    assert matches(r, listing(stickers=["Katowice 2014 | Titan (Holo)"])) is True
    assert matches(r, listing(stickers=["Dust 2 sticker"])) is False


def test_match_discount():
    assert matches(rule(min_discount=0.2), listing(price=70, ref_price=100)) is True   # −30%
    assert matches(rule(min_discount=0.4), listing(price=70, ref_price=100)) is False  # только −30%
    assert matches(rule(min_discount=0.2), listing(price=70, ref_price=None)) is False


# ── защита ────────────────────────────────────────────────────────────
def _limits(**kw):
    base = dict(max_item_price=50.0, daily_limit=100.0, min_balance=0.0)
    base.update(kw)
    return SafetyLimits(**base)


def test_safety_autobuy_off():
    ok, _ = evaluate_buy(10, autobuy=False, balance=100, spent_today=0, limits=_limits())
    assert ok is False


def test_safety_over_item_cap():
    ok, why = evaluate_buy(60, autobuy=True, balance=100, spent_today=0, limits=_limits(max_item_price=50))
    assert ok is False and "лимит" in why


def test_safety_daily_limit():
    ok, _ = evaluate_buy(30, autobuy=True, balance=100, spent_today=80, limits=_limits(daily_limit=100))
    assert ok is False


def test_safety_balance_unknown():
    ok, _ = evaluate_buy(10, autobuy=True, balance=None, spent_today=0, limits=_limits())
    assert ok is False


def test_safety_min_balance_guard():
    ok, _ = evaluate_buy(10, autobuy=True, balance=15, spent_today=0, limits=_limits(min_balance=10))
    assert ok is False  # 15-10 = 5 < 10


def test_safety_ok():
    ok, why = evaluate_buy(20, autobuy=True, balance=100, spent_today=0, limits=_limits())
    assert ok is True and why == "ok"


# ── mock-маркет ───────────────────────────────────────────────────────
async def test_mock_buy_and_dedup():
    m = MockMarket(listings=[listing(listing_id="a", price=20)], balance=100)
    r1 = await m.buy(listing(listing_id="a", price=20))
    assert r1.ok and m.balance == 80
    r2 = await m.buy(listing(listing_id="a", price=20))  # уже куплен
    assert r2.ok is False


async def test_mock_insufficient_balance():
    m = MockMarket(listings=[listing(listing_id="a", price=200)], balance=100)
    res = await m.buy(listing(listing_id="a", price=200))
    assert res.ok is False


# ── парсеры площадок ──────────────────────────────────────────────────
def test_steam_parse():
    data = {"results": [{"name": "AK-47 | Redline (FT)", "hash_name": "AK-47 | Redline (FT)",
                         "sell_price": 1234, "sell_listings": 7}]}
    items = SteamMarket.parse_search(data)
    assert len(items) == 1 and items[0].price == 12.34 and items[0].market == "steam"


def test_dmarket_parse():
    data = {"objects": [{"itemId": "off1", "title": "AK-47 | Case Hardened (FT)",
                         "price": {"USD": "2500"},
                         "extra": {"floatValue": 0.15, "paintSeed": 661,
                                   "stickers": [{"name": "Katowice 2014"}]}}]}
    items = DMarketMarket.parse_items(data)
    assert len(items) == 1
    it = items[0]
    assert it.price == 25.0 and it.paint_seed == 661 and it.float_value == 0.15
    assert it.stickers == ["Katowice 2014"] and it.listing_id == "off1"


# ── БД ────────────────────────────────────────────────────────────────
async def test_db_rules_and_settings(db):
    rid = await db.add_rule(rule(seeds=[661, 670], stickers=["Holo"]))
    got = await db.get_rule(rid)
    assert got.seeds == [661, 670] and got.stickers == ["Holo"]
    assert len(await db.list_rules(only_active=True)) == 1
    await db.set_rule_active(rid, False)
    assert len(await db.list_rules(only_active=True)) == 0
    # settings defaults
    assert await db.get_bool("dry_run") is True
    assert await db.get_bool("autobuy") is False
    await db.set_setting("autobuy", "1")
    assert await db.get_bool("autobuy") is True


async def test_db_seen_and_spend(db):
    assert await db.is_seen("mock", "x") is False
    await db.mark_seen("mock", "x")
    assert await db.is_seen("mock", "x") is True
    await db.add_purchase("mock", "x", "item", 20.0, "bought")
    await db.add_purchase("mock", "y", "item2", 5.0, "dry_run")  # не считается
    assert await db.spent_today() == 20.0


# ── монитор end-to-end ────────────────────────────────────────────────
async def test_monitor_dry_run(db):
    await db.add_rule(rule(name_query="Case Hardened", max_price=100, autobuy=True))
    await db.set_setting("autobuy", "1")   # dry_run остаётся ВКЛ по умолчанию
    market = MockMarket(listings=[listing(listing_id="a", price=20)], balance=100)
    bot = FakeBot()

    await monitor.run_once(bot, CONFIG, db, [market])

    assert any("Найден лот" in t for _, t in bot.msgs)           # алерт ушёл
    assert any("DRY-RUN" in t for _, t in bot.msgs)              # покупка симулирована
    assert market.balance == 100                                 # деньги НЕ потрачены
    rows = await db.recent_purchases()
    assert rows and rows[0]["status"] == "dry_run"


async def test_monitor_real_buy_via_mock(db):
    await db.add_rule(rule(max_price=100, autobuy=True))
    await db.set_setting("autobuy", "1")
    await db.set_setting("dry_run", "0")   # реальная покупка (в mock)
    market = MockMarket(listings=[listing(listing_id="a", price=20)], balance=100)
    bot = FakeBot()

    await monitor.run_once(bot, CONFIG, db, [market])

    assert market.balance == 80                                  # списано
    assert len(market.bought) == 1
    rows = await db.recent_purchases()
    assert rows[0]["status"] == "bought"
    assert await db.spent_today() == 20.0


async def test_monitor_safety_blocks_expensive(db):
    await db.add_rule(rule(max_price=1000, autobuy=True))
    await db.set_setting("autobuy", "1")
    await db.set_setting("dry_run", "0")
    await db.set_setting("max_item_price", "50")   # лимит за предмет 50$
    market = MockMarket(listings=[listing(listing_id="a", price=200)], balance=1000)
    bot = FakeBot()

    await monitor.run_once(bot, CONFIG, db, [market])

    assert market.balance == 1000                                # не куплено
    rows = await db.recent_purchases()
    assert rows[0]["status"] == "skipped"
    assert any("Пропущено" in t for _, t in bot.msgs)


async def test_monitor_alert_only_when_rule_no_autobuy(db):
    await db.add_rule(rule(max_price=100, autobuy=False))   # только алерт
    await db.set_setting("autobuy", "1")
    await db.set_setting("dry_run", "0")
    market = MockMarket(listings=[listing(listing_id="a", price=20)], balance=100)
    bot = FakeBot()

    await monitor.run_once(bot, CONFIG, db, [market])

    assert market.balance == 100
    assert await db.recent_purchases() == []                     # покупок нет
    assert any("Найден лот" in t for _, t in bot.msgs)           # но алерт есть


async def test_monitor_dedup(db):
    await db.add_rule(rule(max_price=100, autobuy=False))
    market = MockMarket(listings=[listing(listing_id="a", price=20)], balance=100)
    bot = FakeBot()
    await monitor.run_once(bot, CONFIG, db, [market])
    n = len(bot.msgs)
    await monitor.run_once(bot, CONFIG, db, [market])   # тот же лот — не дублируем
    assert len(bot.msgs) == n
