"""Асинхронный слой доступа к данным на SQLite (aiosqlite).

Таблицы:
  users       — покупатели
  categories  — категории и подкатегории (parent_id → дерево)
  products     — товары (позиции каталога)
  stock        — единицы «наличия»: одна строка = один выдаваемый товар
                 (например, одна учётная запись «логин:пароль»).
                 state: 0 = свободна, 1 = зарезервирована, 2 = продана
  orders       — заказы (status: pending / paid / rejected / refunded)
  promocodes   — промокоды (скидки)
  reviews      — отзывы покупателей
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Optional

import aiosqlite

# Состояния единицы наличия.
STOCK_FREE = 0
STOCK_RESERVED = 1
STOCK_SOLD = 2

# Таблицы создаются ПЕРВЫМИ, до миграций и индексов, чтобы на старой БД можно
# было доальтерить колонки, прежде чем на них строить индексы.
SCHEMA_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    first_name TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    parent_id  INTEGER REFERENCES categories(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    price       INTEGER NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stock (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    payload     TEXT    NOT NULL,
    state       INTEGER NOT NULL DEFAULT 0,
    order_id    INTEGER,
    created_at  INTEGER NOT NULL,
    reserved_at INTEGER,
    sold_at     INTEGER
);

CREATE TABLE IF NOT EXISTS orders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    product_id     INTEGER NOT NULL,
    stock_id       INTEGER,
    title          TEXT    NOT NULL,
    price          INTEGER NOT NULL,
    original_price INTEGER NOT NULL DEFAULT 0,
    currency       TEXT    NOT NULL,
    method         TEXT    NOT NULL DEFAULT '',
    promo_code     TEXT,
    charge_id      TEXT,
    status         TEXT    NOT NULL DEFAULT 'paid',
    created_at     INTEGER NOT NULL,
    paid_at        INTEGER
);

CREATE TABLE IF NOT EXISTS promocodes (
    code           TEXT PRIMARY KEY,
    discount_type  TEXT    NOT NULL,          -- 'percent' | 'fixed'
    discount_value INTEGER NOT NULL,
    max_uses       INTEGER NOT NULL DEFAULT 0, -- 0 = без лимита
    used_count     INTEGER NOT NULL DEFAULT 0,
    expires_at     INTEGER,                    -- NULL = бессрочно
    is_active      INTEGER NOT NULL DEFAULT 1,
    created_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    rating     INTEGER NOT NULL,
    text       TEXT    NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
"""

# Индексы создаются ПОСЛЕ миграций (когда все колонки гарантированно есть).
SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);
CREATE INDEX IF NOT EXISTS idx_stock_state ON stock(product_id, state);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, status);
CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id);
"""

# Колонки, которые могли отсутствовать в более ранней версии БД.
_MIGRATIONS: list[tuple[str, str, str]] = [
    ("products", "category_id", "ALTER TABLE products ADD COLUMN category_id INTEGER"),
    ("stock", "state", "ALTER TABLE stock ADD COLUMN state INTEGER NOT NULL DEFAULT 0"),
    ("stock", "reserved_at", "ALTER TABLE stock ADD COLUMN reserved_at INTEGER"),
    ("orders", "original_price", "ALTER TABLE orders ADD COLUMN original_price INTEGER NOT NULL DEFAULT 0"),
    ("orders", "method", "ALTER TABLE orders ADD COLUMN method TEXT NOT NULL DEFAULT ''"),
    ("orders", "promo_code", "ALTER TABLE orders ADD COLUMN promo_code TEXT"),
    ("orders", "paid_at", "ALTER TABLE orders ADD COLUMN paid_at INTEGER"),
]


class Database:
    def __init__(self, path: Path, currency: str = "XTR") -> None:
        self.path = Path(path)
        self.currency = currency
        self._conn: Optional[aiosqlite.Connection] = None
        # Полностью сериализуем операции с наличием, чтобы одну и ту же единицу
        # нельзя было продать/зарезервировать дважды при одновременных запросах.
        self._stock_lock = asyncio.Lock()

    # ── жизненный цикл ────────────────────────────────────────────────
    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA_TABLES)
        await self._migrate()
        await self._conn.executescript(SCHEMA_INDEXES)
        await self._conn.commit()

    async def _migrate(self) -> None:
        for table, column, ddl in _MIGRATIONS:
            cur = await self._conn.execute(f"PRAGMA table_info({table})")
            cols = {row["name"] for row in await cur.fetchall()}
            if column not in cols:
                await self._conn.execute(ddl)
        # Перенос из старой схемы stock.is_sold → state.
        cur = await self._conn.execute("PRAGMA table_info(stock)")
        cols = {row["name"] for row in await cur.fetchall()}
        if "is_sold" in cols:
            await self._conn.execute(
                "UPDATE stock SET state = 2 WHERE is_sold = 1 AND state = 0"
            )

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
                username = excluded.username, first_name = excluded.first_name
            """,
            (user_id, username, first_name, int(time.time())),
        )
        await self.conn.commit()

    async def all_user_ids(self) -> list[int]:
        cur = await self.conn.execute("SELECT user_id FROM users")
        return [row["user_id"] for row in await cur.fetchall()]

    # ── категории ─────────────────────────────────────────────────────
    async def add_category(self, name: str, parent_id: int | None) -> int:
        cur = await self.conn.execute(
            "INSERT INTO categories(name, parent_id, created_at) VALUES(?, ?, ?)",
            (name, parent_id, int(time.time())),
        )
        await self.conn.commit()
        return int(cur.lastrowid)

    async def get_category(self, category_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,))
        return await cur.fetchone()

    async def list_categories(self, parent_id: int | None) -> list[aiosqlite.Row]:
        if parent_id is None:
            cur = await self.conn.execute(
                "SELECT * FROM categories WHERE parent_id IS NULL ORDER BY name"
            )
        else:
            cur = await self.conn.execute(
                "SELECT * FROM categories WHERE parent_id = ? ORDER BY name", (parent_id,)
            )
        return list(await cur.fetchall())

    async def all_categories(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM categories ORDER BY parent_id, name")
        return list(await cur.fetchall())

    async def delete_category(self, category_id: int) -> None:
        await self.conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        await self.conn.commit()

    async def category_path(self, category_id: int | None) -> str:
        """Путь категории для показа: 'Аккаунты › Instagram'. '' — если нет."""
        if not category_id:
            return ""
        names: list[str] = []
        seen: set[int] = set()
        cur_id: int | None = category_id
        while cur_id and cur_id not in seen:
            seen.add(cur_id)
            row = await self.get_category(cur_id)
            if row is None:
                break
            names.append(row["name"])
            cur_id = row["parent_id"]
        return " › ".join(reversed(names))

    # ── товары ────────────────────────────────────────────────────────
    async def add_product(
        self, title: str, description: str, category_id: int | None, price: int
    ) -> int:
        cur = await self.conn.execute(
            "INSERT INTO products(title, description, category_id, price, created_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (title, description, category_id, price, int(time.time())),
        )
        await self.conn.commit()
        return int(cur.lastrowid)

    async def get_product(self, product_id: int | None) -> Optional[aiosqlite.Row]:
        if product_id is None:
            return None
        cur = await self.conn.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        return await cur.fetchone()

    _LIST_SQL = """
        SELECT p.*,
               COALESCE(SUM(CASE WHEN s.state = 0 THEN 1 ELSE 0 END), 0) AS available
        FROM products p
        LEFT JOIN stock s ON s.product_id = p.id
        {where}
        GROUP BY p.id
        ORDER BY p.id
    """

    async def list_all_products(self, only_active: bool = False) -> list[aiosqlite.Row]:
        where = "WHERE p.is_active = 1" if only_active else ""
        cur = await self.conn.execute(self._LIST_SQL.format(where=where))
        return list(await cur.fetchall())

    async def list_products_in_category(
        self, category_id: int | None, only_active: bool = True
    ) -> list[aiosqlite.Row]:
        conds = []
        params: list[Any] = []
        if category_id is None:
            conds.append("p.category_id IS NULL")
        else:
            conds.append("p.category_id = ?")
            params.append(category_id)
        if only_active:
            conds.append("p.is_active = 1")
        where = "WHERE " + " AND ".join(conds)
        cur = await self.conn.execute(self._LIST_SQL.format(where=where), params)
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
            "INSERT INTO stock(product_id, payload, created_at) VALUES(?, ?, ?)", rows
        )
        await self.conn.commit()
        return len(rows)

    async def available_count(self, product_id: int) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS c FROM stock WHERE product_id = ? AND state = 0",
            (product_id,),
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def _create_order(
        self, product: aiosqlite.Row, user_id: int, price: int, original_price: int,
        method: str, promo_code: str | None, charge_id: str | None, status: str,
    ) -> int:
        now = int(time.time())
        paid_at = now if status == "paid" else None
        cur = await self.conn.execute(
            "INSERT INTO orders(user_id, product_id, stock_id, title, price, original_price, "
            "currency, method, promo_code, charge_id, status, created_at, paid_at) "
            "VALUES(?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, product["id"], product["title"], price, original_price,
             self.currency, method, promo_code, charge_id, status, now, paid_at),
        )
        return int(cur.lastrowid)

    async def deliver_one(
        self, product: aiosqlite.Row, user_id: int, charge_id: str | None,
        price: int, original_price: int, method: str, promo_code: str | None = None,
    ) -> Optional[dict[str, Any]]:
        """Мгновенная выдача (stars/provider): взять свободную единицу, создать
        оплаченный заказ, пометить единицу проданной. None — если наличие кончилось.
        """
        async with self._stock_lock:
            cur = await self.conn.execute(
                "SELECT id, payload FROM stock WHERE product_id = ? AND state = 0 "
                "ORDER BY id LIMIT 1",
                (product["id"],),
            )
            item = await cur.fetchone()
            if item is None:
                return None
            order_id = await self._create_order(
                product, user_id, price, original_price, method, promo_code, charge_id, "paid"
            )
            now = int(time.time())
            await self.conn.execute(
                "UPDATE stock SET state = 2, order_id = ?, sold_at = ? WHERE id = ?",
                (order_id, now, item["id"]),
            )
            await self.conn.execute(
                "UPDATE orders SET stock_id = ? WHERE id = ?", (item["id"], order_id)
            )
            await self.conn.commit()
            return {"order_id": order_id, "stock_id": item["id"], "payload": item["payload"]}

    async def reserve_one(
        self, product: aiosqlite.Row, user_id: int, price: int, original_price: int,
        method: str, promo_code: str | None = None,
    ) -> Optional[dict[str, Any]]:
        """Ручная оплата: создать заказ pending и зарезервировать под него единицу.
        None — если наличие кончилось. Резерв держится до подтверждения/отклонения.
        """
        async with self._stock_lock:
            cur = await self.conn.execute(
                "SELECT id FROM stock WHERE product_id = ? AND state = 0 ORDER BY id LIMIT 1",
                (product["id"],),
            )
            item = await cur.fetchone()
            if item is None:
                return None
            order_id = await self._create_order(
                product, user_id, price, original_price, method, promo_code, None, "pending"
            )
            now = int(time.time())
            await self.conn.execute(
                "UPDATE stock SET state = 1, order_id = ?, reserved_at = ? WHERE id = ?",
                (order_id, now, item["id"]),
            )
            await self.conn.execute(
                "UPDATE orders SET stock_id = ? WHERE id = ?", (item["id"], order_id)
            )
            await self.conn.commit()
            return {"order_id": order_id, "stock_id": item["id"]}

    async def approve_order(self, order_id: int) -> Optional[dict[str, Any]]:
        """Подтвердить оплату pending-заказа: пометить единицу проданной,
        заказ — оплаченным. Возвращает выданный товар или None.
        """
        async with self._stock_lock:
            order = await self.get_order(order_id)
            if order is None or order["status"] != "pending":
                return None
            cur = await self.conn.execute(
                "SELECT id, payload FROM stock WHERE id = ? AND state = 1",
                (order["stock_id"],),
            )
            item = await cur.fetchone()
            if item is None:
                return None
            now = int(time.time())
            await self.conn.execute(
                "UPDATE stock SET state = 2, sold_at = ? WHERE id = ?", (now, item["id"])
            )
            await self.conn.execute(
                "UPDATE orders SET status = 'paid', paid_at = ? WHERE id = ?", (now, order_id)
            )
            await self.conn.commit()
            return {
                "order_id": order_id, "payload": item["payload"],
                "user_id": order["user_id"], "title": order["title"],
                "price": order["price"], "promo_code": order["promo_code"],
            }

    async def reject_order(self, order_id: int) -> Optional[aiosqlite.Row]:
        """Отклонить pending-заказ: вернуть зарезервированную единицу в наличие."""
        async with self._stock_lock:
            order = await self.get_order(order_id)
            if order is None or order["status"] != "pending":
                return None
            if order["stock_id"] is not None:
                await self.conn.execute(
                    "UPDATE stock SET state = 0, order_id = NULL, reserved_at = NULL "
                    "WHERE id = ? AND state = 1",
                    (order["stock_id"],),
                )
            await self.conn.execute(
                "UPDATE orders SET status = 'rejected' WHERE id = ?", (order_id,)
            )
            await self.conn.commit()
            return order

    async def get_order(self, order_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        return await cur.fetchone()

    async def get_user_orders(self, user_id: int, limit: int = 20) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            """
            SELECT o.*, s.payload
            FROM orders o
            LEFT JOIN stock s ON s.id = o.stock_id
            WHERE o.user_id = ? AND o.status = 'paid'
            ORDER BY o.id DESC LIMIT ?
            """,
            (user_id, limit),
        )
        return list(await cur.fetchall())

    async def has_purchased(self, user_id: int, product_id: int) -> bool:
        cur = await self.conn.execute(
            "SELECT 1 FROM orders WHERE user_id = ? AND product_id = ? AND status = 'paid' LIMIT 1",
            (user_id, product_id),
        )
        return await cur.fetchone() is not None

    async def stats(self) -> dict[str, int]:
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS orders, COALESCE(SUM(price), 0) AS revenue "
            "FROM orders WHERE status = 'paid'"
        )
        o = await cur.fetchone()
        cur = await self.conn.execute("SELECT COUNT(*) AS c FROM users")
        u = await cur.fetchone()
        cur = await self.conn.execute("SELECT COUNT(*) AS c FROM stock WHERE state = 0")
        s = await cur.fetchone()
        return {
            "orders": int(o["orders"]) if o else 0,
            "revenue": int(o["revenue"]) if o else 0,
            "users": int(u["c"]) if u else 0,
            "stock": int(s["c"]) if s else 0,
        }

    # ── промокоды ─────────────────────────────────────────────────────
    async def add_promocode(
        self, code: str, discount_type: str, discount_value: int,
        max_uses: int = 0, expires_at: int | None = None,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO promocodes(code, discount_type, discount_value, max_uses, "
            "expires_at, created_at) VALUES(?, ?, ?, ?, ?, ?)",
            (code, discount_type, discount_value, max_uses, expires_at, int(time.time())),
        )
        await self.conn.commit()

    async def get_promocode(self, code: str) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM promocodes WHERE code = ?", (code.upper(),)
        )
        return await cur.fetchone()

    async def valid_promocode(self, code: str) -> Optional[aiosqlite.Row]:
        promo = await self.get_promocode(code)
        if promo is None or not promo["is_active"]:
            return None
        if promo["expires_at"] is not None and promo["expires_at"] < int(time.time()):
            return None
        if promo["max_uses"] and promo["used_count"] >= promo["max_uses"]:
            return None
        return promo

    async def use_promocode(self, code: str) -> None:
        await self.conn.execute(
            "UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?", (code.upper(),)
        )
        await self.conn.commit()

    async def list_promocodes(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM promocodes ORDER BY created_at DESC")
        return list(await cur.fetchall())

    async def delete_promocode(self, code: str) -> None:
        await self.conn.execute("DELETE FROM promocodes WHERE code = ?", (code.upper(),))
        await self.conn.commit()

    # ── отзывы ────────────────────────────────────────────────────────
    async def add_review(self, user_id: int, product_id: int, rating: int, text: str) -> int:
        cur = await self.conn.execute(
            "INSERT INTO reviews(user_id, product_id, rating, text, created_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (user_id, product_id, rating, text, int(time.time())),
        )
        await self.conn.commit()
        return int(cur.lastrowid)

    async def product_rating(self, product_id: int) -> tuple[float, int]:
        cur = await self.conn.execute(
            "SELECT AVG(rating) AS avg, COUNT(*) AS c FROM reviews WHERE product_id = ?",
            (product_id,),
        )
        row = await cur.fetchone()
        if not row or row["c"] == 0:
            return (0.0, 0)
        return (float(row["avg"]), int(row["c"]))

    async def list_product_reviews(self, product_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM reviews WHERE product_id = ? ORDER BY id DESC LIMIT ?",
            (product_id, limit),
        )
        return list(await cur.fetchall())

    async def list_recent_reviews(self, limit: int = 15) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            """
            SELECT r.*, p.title AS product_title
            FROM reviews r LEFT JOIN products p ON p.id = r.product_id
            ORDER BY r.id DESC LIMIT ?
            """,
            (limit,),
        )
        return list(await cur.fetchall())
