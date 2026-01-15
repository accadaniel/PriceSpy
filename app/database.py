import asyncpg
from typing import Optional, List
from datetime import datetime
from .config import get_settings

# Connection pool
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """Get or create database connection pool."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=1,
            max_size=10
        )
    return _pool


async def init_db():
    """Initialize the database with required tables."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        # Create products table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
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
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Create price_history table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id SERIAL PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                retailer TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT DEFAULT 'USD',
                url TEXT NOT NULL,
                scraped_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Create alerts_sent table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts_sent (
                id SERIAL PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                price REAL NOT NULL,
                retailer TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Create index
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_price_history_product
            ON price_history(product_id, scraped_at DESC)
        """)


async def close_db():
    """Close database connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


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
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO products (name, search_query, category, region, size, color, brand, model, storage, material, target_price, currency, user_email)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING id
            """,
            name, search_query, category, region, size, color, brand, model, storage, material, target_price, currency, user_email
        )
        return row['id']


async def get_product(product_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM products WHERE id = $1",
            product_id
        )
        if row:
            return dict(row)
        return None


async def get_all_products(active_only: bool = False) -> List[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if active_only:
            rows = await conn.fetch(
                "SELECT * FROM products WHERE is_active = TRUE ORDER BY created_at DESC"
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM products ORDER BY created_at DESC"
            )
        return [dict(row) for row in rows]


async def update_product(product_id: int, **kwargs) -> bool:
    if not kwargs:
        return False

    pool = await get_pool()

    # Build dynamic update query
    set_clauses = []
    values = []
    for i, (key, value) in enumerate(kwargs.items(), start=1):
        set_clauses.append(f"{key} = ${i}")
        values.append(value)

    values.append(product_id)
    query = f"UPDATE products SET {', '.join(set_clauses)} WHERE id = ${len(values)}"

    async with pool.acquire() as conn:
        result = await conn.execute(query, *values)
        return result != "UPDATE 0"


async def delete_product(product_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM products WHERE id = $1",
            product_id
        )
        return result != "DELETE 0"


# Price history operations
async def add_price_record(
    product_id: int,
    retailer: str,
    price: float,
    url: str,
    currency: str = "USD"
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO price_history (product_id, retailer, price, currency, url)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            product_id, retailer, price, currency, url
        )
        return row['id']


async def get_price_history(product_id: int, limit: int = 50) -> List[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM price_history
            WHERE product_id = $1
            ORDER BY scraped_at DESC
            LIMIT $2
            """,
            product_id, limit
        )
        return [dict(row) for row in rows]


async def get_lowest_price(product_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM price_history
            WHERE product_id = $1
            ORDER BY price ASC
            LIMIT 1
            """,
            product_id
        )
        if row:
            return dict(row)
        return None


async def get_latest_prices(product_id: int) -> List[dict]:
    """Get the most recent price from each retailer for a product."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (retailer) *
            FROM price_history
            WHERE product_id = $1
            ORDER BY retailer, scraped_at DESC
            """,
            product_id
        )
        # Sort by price after getting distinct retailers
        return sorted([dict(row) for row in rows], key=lambda x: x['price'])


# Alert operations
async def add_alert_record(product_id: int, price: float, retailer: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO alerts_sent (product_id, price, retailer)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            product_id, price, retailer
        )
        return row['id']


async def get_recent_alert(product_id: int, hours: int = 24) -> Optional[dict]:
    """Check if an alert was sent recently for this product."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM alerts_sent
            WHERE product_id = $1
            AND sent_at > NOW() - INTERVAL '%s hours'
            ORDER BY sent_at DESC
            LIMIT 1
            """ % hours,
            product_id
        )
        if row:
            return dict(row)
        return None
