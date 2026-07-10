"""SQLite: правила, антидубли (seen), покупки, настройки-переключатели."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import aiosqlite

from .models import Rule

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name_query   TEXT    NOT NULL,
    max_price    REAL    NOT NULL,
    min_float    REAL,
    max_float    REAL,
    seeds        TEXT    NOT NULL DEFAULT '',
    stickers     TEXT    NOT NULL DEFAULT '',
    min_discount REAL    NOT NULL DEFAULT 0,
    autobuy      INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS seen (
    market     TEXT NOT NULL,
    listing_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (market, listing_id)
);

CREATE TABLE IF NOT EXISTS purchases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    market     TEXT NOT NULL,
    listing_id TEXT NOT NULL,
    name       TEXT NOT NULL,
    price      REAL NOT NULL,
    status     TEXT NOT NULL,      -- bought | dry_run | failed
    note       TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_purchases_time ON purchases(created_at);
"""

_SETTING_DEFAULTS = {
    "monitoring": lambda c: "1",
    "autobuy": lambda c: "1" if c.default_autobuy else "0",
    "dry_run": lambda c: "1" if c.default_dry_run else "0",
    "max_item_price": lambda c: str(c.default_max_item_price),
    "daily_limit": lambda c: str(c.default_daily_limit),
    "min_balance": lambda c: str(c.default_min_balance),
}


def _seeds_to_str(seeds: list[int]) -> str:
    return ",".join(str(s) for s in seeds)


def _seeds_from_str(raw: str) -> list[int]:
    return [int(p) for p in raw.split(",") if p.strip().lstrip("-").isdigit()]


def _stickers_to_str(stickers: list[str]) -> str:
    return "\n".join(s.strip() for s in stickers if s.strip())


def _stickers_from_str(raw: str) -> list[str]:
    return [s for s in raw.split("\n") if s.strip()]


def _row_to_rule(row: aiosqlite.Row) -> Rule:
    return Rule(
        id=row["id"],
        name_query=row["name_query"],
        max_price=row["max_price"],
        min_float=row["min_float"],
        max_float=row["max_float"],
        seeds=_seeds_from_str(row["seeds"]),
        stickers=_stickers_from_str(row["stickers"]),
        min_discount=row["min_discount"],
        autobuy=bool(row["autobuy"]),
        active=bool(row["active"]),
    )


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self, config) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(SCHEMA)
        for key, factory in _SETTING_DEFAULTS.items():
            await self._conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (key, factory(config))
            )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() ещё не вызван")
        return self._conn

    # ── настройки-переключатели ───────────────────────────────────────
    async def get_setting(self, key: str, default: str = "") -> str:
        cur = await self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self.conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self.conn.commit()

    async def get_bool(self, key: str) -> bool:
        return (await self.get_setting(key, "0")) == "1"

    async def get_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(await self.get_setting(key, str(default)))
        except ValueError:
            return default

    # ── правила ───────────────────────────────────────────────────────
    async def add_rule(self, rule: Rule) -> int:
        cur = await self.conn.execute(
            "INSERT INTO rules(name_query, max_price, min_float, max_float, seeds, stickers, "
            "min_discount, autobuy, active, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (rule.name_query, rule.max_price, rule.min_float, rule.max_float,
             _seeds_to_str(rule.seeds), _stickers_to_str(rule.stickers),
             rule.min_discount, 1 if rule.autobuy else 0, int(time.time())),
        )
        await self.conn.commit()
        return int(cur.lastrowid)

    async def list_rules(self, only_active: bool = False) -> list[Rule]:
        sql = "SELECT * FROM rules"
        if only_active:
            sql += " WHERE active = 1"
        sql += " ORDER BY id"
        cur = await self.conn.execute(sql)
        return [_row_to_rule(r) for r in await cur.fetchall()]

    async def get_rule(self, rule_id: int) -> Optional[Rule]:
        cur = await self.conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,))
        row = await cur.fetchone()
        return _row_to_rule(row) if row else None

    async def delete_rule(self, rule_id: int) -> None:
        await self.conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
        await self.conn.commit()

    async def set_rule_active(self, rule_id: int, active: bool) -> None:
        await self.conn.execute(
            "UPDATE rules SET active = ? WHERE id = ?", (1 if active else 0, rule_id)
        )
        await self.conn.commit()

    # ── антидубли ─────────────────────────────────────────────────────
    async def is_seen(self, market: str, listing_id: str) -> bool:
        cur = await self.conn.execute(
            "SELECT 1 FROM seen WHERE market = ? AND listing_id = ?", (market, listing_id)
        )
        return await cur.fetchone() is not None

    async def mark_seen(self, market: str, listing_id: str) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO seen(market, listing_id, created_at) VALUES(?, ?, ?)",
            (market, listing_id, int(time.time())),
        )
        await self.conn.commit()

    async def prune_seen(self, older_than_days: int = 7) -> None:
        cutoff = int(time.time()) - older_than_days * 86400
        await self.conn.execute("DELETE FROM seen WHERE created_at < ?", (cutoff,))
        await self.conn.commit()

    # ── покупки / траты ───────────────────────────────────────────────
    async def add_purchase(self, market: str, listing_id: str, name: str, price: float,
                           status: str, note: str = "") -> None:
        await self.conn.execute(
            "INSERT INTO purchases(market, listing_id, name, price, status, note, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (market, listing_id, name, price, status, note, int(time.time())),
        )
        await self.conn.commit()

    async def spent_today(self) -> float:
        day_start = int(time.time()) - (int(time.time()) % 86400)
        cur = await self.conn.execute(
            "SELECT COALESCE(SUM(price), 0) AS s FROM purchases "
            "WHERE status = 'bought' AND created_at >= ?",
            (day_start,),
        )
        row = await cur.fetchone()
        return float(row["s"]) if row else 0.0

    async def recent_purchases(self, limit: int = 15) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM purchases ORDER BY id DESC LIMIT ?", (limit,)
        )
        return list(await cur.fetchall())
