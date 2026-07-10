"""Асинхронный слой доступа к данным на SQLite (aiosqlite).

Таблицы:
  users    — покупатели
  products — товары (позиции каталога)
  stock    — единицы «наличия»: одна строка = один выдаваемый товар
             (например, одна учётная запись «логин:пароль»)
  orders   — оплаченные заказы
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Optional

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    first_name TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    category    TEXT    NOT NULL DEFAULT '',
    price       INTEGER NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stock (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    payload    TEXT    NOT NULL,
    is_sold    INTEGER NOT NULL DEFAULT 0,
    order_id   INTEGER,
    created_at INTEGER NOT NULL,
    sold_at    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_stock_available ON stock(product_id, is_sold);

CREATE TABLE IF NOT EXISTS orders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    stock_id   INTEGER,
    title      TEXT    NOT NULL,
    price      INTEGER NOT NULL,
    currency   TEXT    NOT NULL,
    charge_id  TEXT,
    status     TEXT    NOT NULL DEFAULT 'paid',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
"""


class Database:
    def __init__(self, path: Path, currency: str = "XTR") -> None:
        self.path = Path(path)
        self.currency = currency
        self._conn: Optional[aiosqlite.Connection] = None
        # Полностью сериализуем выдачу товара, чтобы одну и ту же единицу
        # наличия нельзя было продать дважды при одновременных оплатах.
        self._deliver_lock = asyncio.Lock()

    # ── жизненный цикл ────────────────────────────────────────────────
    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)
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

    # ── пользователи ──────────────────────────────────────────────────
    async def upsert_user(self, user_id: int, username: str | None, first_name: str | None) -> None:
        await self.conn.execute(
            """
            INSERT INTO users(user_id, username, first_name, created_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name
            """,
            (user_id, username, first_name, int(time.time())),
        )
        await self.conn.commit()

    # ── товары ────────────────────────────────────────────────────────
    async def add_product(
        self, title: str, description: str, category: str, price: int
    ) -> int:
        cur = await self.conn.execute(
            "INSERT INTO products(title, description, category, price, created_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (title, description, category, price, int(time.time())),
        )
        await self.conn.commit()
        return int(cur.lastrowid)

    async def get_product(self, product_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        return await cur.fetchone()

    async def list_products(self, only_active: bool = True) -> list[aiosqlite.Row]:
        """Товары вместе с количеством доступных единиц наличия (available)."""
        where = "WHERE p.is_active = 1" if only_active else ""
        cur = await self.conn.execute(
            f"""
            SELECT p.*,
                   COALESCE(SUM(CASE WHEN s.is_sold = 0 THEN 1 ELSE 0 END), 0) AS available
            FROM products p
            LEFT JOIN stock s ON s.product_id = p.id
            {where}
            GROUP BY p.id
            ORDER BY p.category, p.id
            """
        )
        return list(await cur.fetchall())

    async def set_product_active(self, product_id: int, is_active: bool) -> None:
        await self.conn.execute(
            "UPDATE products SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, product_id),
        )
        await self.conn.commit()

    async def delete_product(self, product_id: int) -> None:
        await self.conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        await self.conn.commit()

    # ── наличие (stock) ───────────────────────────────────────────────
    async def add_stock(self, product_id: int, items: list[str]) -> int:
        now = int(time.time())
        rows = [(product_id, item, now) for item in items if item.strip()]
        if not rows:
            return 0
        await self.conn.executemany(
            "INSERT INTO stock(product_id, payload, created_at) VALUES(?, ?, ?)",
            rows,
        )
        await self.conn.commit()
        return len(rows)

    async def available_count(self, product_id: int) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS c FROM stock WHERE product_id = ? AND is_sold = 0",
            (product_id,),
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def deliver_one(
        self, product: aiosqlite.Row, user_id: int, charge_id: str | None
    ) -> Optional[dict[str, Any]]:
        """Атомарно: взять одну свободную единицу наличия, создать заказ,
        пометить единицу проданной. Возвращает выданный товар или None,
        если наличие закончилось (тогда покупателю нужно вернуть оплату).
        """
        async with self._deliver_lock:
            cur = await self.conn.execute(
                "SELECT id, payload FROM stock "
                "WHERE product_id = ? AND is_sold = 0 ORDER BY id LIMIT 1",
                (product["id"],),
            )
            item = await cur.fetchone()
            if item is None:
                return None

            now = int(time.time())
            cur = await self.conn.execute(
                "INSERT INTO orders(user_id, product_id, stock_id, title, price, "
                "currency, charge_id, status, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, 'paid', ?)",
                (
                    user_id,
                    product["id"],
                    item["id"],
                    product["title"],
                    product["price"],
                    self.currency,
                    charge_id,
                    now,
                ),
            )
            order_id = int(cur.lastrowid)
            await self.conn.execute(
                "UPDATE stock SET is_sold = 1, order_id = ?, sold_at = ? WHERE id = ?",
                (order_id, now, item["id"]),
            )
            await self.conn.commit()
            return {"order_id": order_id, "stock_id": item["id"], "payload": item["payload"]}

    # ── заказы / статистика ───────────────────────────────────────────
    async def get_user_orders(self, user_id: int, limit: int = 20) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            """
            SELECT o.*, s.payload
            FROM orders o
            LEFT JOIN stock s ON s.id = o.stock_id
            WHERE o.user_id = ?
            ORDER BY o.id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return list(await cur.fetchall())

    async def stats(self) -> dict[str, int]:
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS orders, COALESCE(SUM(price), 0) AS revenue FROM orders "
            "WHERE status = 'paid'"
        )
        o = await cur.fetchone()
        cur = await self.conn.execute("SELECT COUNT(*) AS c FROM users")
        u = await cur.fetchone()
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS c FROM stock WHERE is_sold = 0"
        )
        s = await cur.fetchone()
        return {
            "orders": int(o["orders"]) if o else 0,
            "revenue": int(o["revenue"]) if o else 0,
            "users": int(u["c"]) if u else 0,
            "stock": int(s["c"]) if s else 0,
        }
