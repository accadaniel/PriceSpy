import aiosqlite
import os
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from .config import get_settings


async def get_db_path() -> str:
    settings = get_settings()
    db_path = settings.database_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return db_path


async def init_db():
    """Initialize the database with required tables."""
    db_path = await get_db_path()

    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                search_query TEXT NOT NULL,
                category TEXT DEFAULT 'electronics',
                region TEXT DEFAULT 'eu',
                size TEXT,
                color TEXT,
                brand TEXT,
                model TEXT,
                storage TEXT,
                material TEXT,
                target_price REAL NOT NULL,
                currency TEXT DEFAULT 'EUR',
                user_email TEXT NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migration: Add new columns if they don't exist
        try:
            await db.execute("ALTER TABLE products ADD COLUMN category TEXT DEFAULT 'electronics'")
        except:
            pass
        try:
            await db.execute("ALTER TABLE products ADD COLUMN region TEXT DEFAULT 'eu'")
        except:
            pass
        try:
            await db.execute("ALTER TABLE products ADD COLUMN brand TEXT")
        except:
            pass
        try:
            await db.execute("ALTER TABLE products ADD COLUMN model TEXT")
        except:
            pass
        try:
            await db.execute("ALTER TABLE products ADD COLUMN storage TEXT")
        except:
            pass
        try:
            await db.execute("ALTER TABLE products ADD COLUMN material TEXT")
        except:
            pass
        try:
            await db.execute("ALTER TABLE products ADD COLUMN currency TEXT DEFAULT 'EUR'")
        except:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                retailer TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT DEFAULT 'USD',
                url TEXT NOT NULL,
                scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS alerts_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                price REAL NOT NULL,
                retailer TEXT NOT NULL,
                sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_price_history_product
            ON price_history(product_id, scraped_at DESC)
        """)

        await db.commit()


async def get_db():
    """Get database connection."""
    db_path = await get_db_path()
    return await aiosqlite.connect(db_path)


# Product CRUD operations
async def create_product(
    name: str,
    search_query: str,
    target_price: float,
    user_email: str,
    category: str = "electronics",
    region: str = "eu",
    size: Optional[str] = None,
    color: Optional[str] = None,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    storage: Optional[str] = None,
    material: Optional[str] = None,
    currency: str = "EUR"
) -> int:
    db_path = await get_db_path()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO products (name, search_query, category, region, size, color, brand, model, storage, material, target_price, currency, user_email)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, search_query, category, region, size, color, brand, model, storage, material, target_price, currency, user_email)
        )
        await db.commit()
        return cursor.lastrowid


async def get_product(product_id: int) -> Optional[dict]:
    db_path = await get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM products WHERE id = ?",
            (product_id,)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None


async def get_all_products(active_only: bool = False) -> List[dict]:
    db_path = await get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM products"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY created_at DESC"
        cursor = await db.execute(query)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_product(product_id: int, **kwargs) -> bool:
    if not kwargs:
        return False

    db_path = await get_db_path()
    fields = ", ".join(f"{k} = ?" for k in kwargs.keys())
    values = list(kwargs.values()) + [product_id]

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            f"UPDATE products SET {fields} WHERE id = ?",
            values
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_product(product_id: int) -> bool:
    db_path = await get_db_path()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "DELETE FROM products WHERE id = ?",
            (product_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


# Price history operations
async def add_price_record(
    product_id: int,
    retailer: str,
    price: float,
    url: str,
    currency: str = "USD"
) -> int:
    db_path = await get_db_path()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO price_history (product_id, retailer, price, currency, url)
            VALUES (?, ?, ?, ?, ?)
            """,
            (product_id, retailer, price, currency, url)
        )
        await db.commit()
        return cursor.lastrowid


async def get_price_history(product_id: int, limit: int = 50) -> List[dict]:
    db_path = await get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM price_history
            WHERE product_id = ?
            ORDER BY scraped_at DESC
            LIMIT ?
            """,
            (product_id, limit)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_lowest_price(product_id: int) -> Optional[dict]:
    db_path = await get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM price_history
            WHERE product_id = ?
            ORDER BY price ASC
            LIMIT 1
            """,
            (product_id,)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None


async def get_latest_prices(product_id: int) -> List[dict]:
    """Get the most recent price from each retailer for a product."""
    db_path = await get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT ph.* FROM price_history ph
            INNER JOIN (
                SELECT retailer, MAX(scraped_at) as max_date
                FROM price_history
                WHERE product_id = ?
                GROUP BY retailer
            ) latest ON ph.retailer = latest.retailer AND ph.scraped_at = latest.max_date
            WHERE ph.product_id = ?
            ORDER BY ph.price ASC
            """,
            (product_id, product_id)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# Alert operations
async def add_alert_record(product_id: int, price: float, retailer: str) -> int:
    db_path = await get_db_path()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO alerts_sent (product_id, price, retailer)
            VALUES (?, ?, ?)
            """,
            (product_id, price, retailer)
        )
        await db.commit()
        return cursor.lastrowid


async def get_recent_alert(product_id: int, hours: int = 24) -> Optional[dict]:
    """Check if an alert was sent recently for this product."""
    db_path = await get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM alerts_sent
            WHERE product_id = ?
            AND sent_at > datetime('now', ?)
            ORDER BY sent_at DESC
            LIMIT 1
            """,
            (product_id, f'-{hours} hours')
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None
