"""SQLite-backed product database for the warehouse intake app.

One file (inventory.db) holding two tables: products (one row per physical
item being processed) and product_images (one row per photo, many per
product). Selling/archiving a product never deletes its row -- only its
status changes -- so sold/listed history is never lost.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

STATUSES = ("draft", "ready", "listed", "sold", "archived")

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT,
    lpn TEXT UNIQUE,
    asin TEXT,
    upc TEXT,
    ean TEXT,
    title TEXT,
    description TEXT,
    condition TEXT,
    category TEXT,
    price TEXT,
    weight TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    shopify_product_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_lpn ON products(lpn);
CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect():
    conn = sqlite3.connect(config.INVENTORY_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _connect() as conn:
        conn.executescript(SCHEMA)


PRODUCT_FIELDS = (
    "sku", "lpn", "asin", "upc", "ean", "title", "description",
    "condition", "category", "price", "weight",
)


def create_product(data):
    now = _now()
    fields = {k: data.get(k) for k in PRODUCT_FIELDS}
    with _connect() as conn:
        cur = conn.execute(
            f"""INSERT INTO products ({', '.join(fields)}, status, created_at, updated_at)
                VALUES ({', '.join('?' for _ in fields)}, 'draft', ?, ?)""",
            (*fields.values(), now, now),
        )
        return cur.lastrowid


def update_product(product_id, data):
    fields = {k: v for k, v in data.items() if k in PRODUCT_FIELDS}
    if not fields:
        return
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as conn:
        conn.execute(
            f"UPDATE products SET {set_clause} WHERE id = ?", (*fields.values(), product_id)
        )


def set_status(product_id, status, shopify_product_id=None):
    if status not in STATUSES:
        raise ValueError(f"Unknown status: {status}")
    with _connect() as conn:
        if shopify_product_id:
            conn.execute(
                "UPDATE products SET status = ?, shopify_product_id = ?, updated_at = ? WHERE id = ?",
                (status, shopify_product_id, _now(), product_id),
            )
        else:
            conn.execute(
                "UPDATE products SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), product_id),
            )


def get_product(product_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            return None
        product = dict(row)
        product["images"] = [dict(r) for r in conn.execute(
            "SELECT * FROM product_images WHERE product_id = ? ORDER BY position", (product_id,)
        )]
        return product


def search_products(query="", status=None, limit=50, offset=0):
    sql = "SELECT * FROM products WHERE 1=1"
    params = []
    if query:
        sql += " AND (sku LIKE ? OR lpn LIKE ? OR asin LIKE ? OR title LIKE ?)"
        like = f"%{query}%"
        params += [like, like, like, like]
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with _connect() as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def add_image(product_id, filename, position=None):
    with _connect() as conn:
        if position is None:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM product_images WHERE product_id = ?",
                (product_id,),
            ).fetchone()
            position = row["next_pos"]
        cur = conn.execute(
            "INSERT INTO product_images (product_id, filename, position, created_at) VALUES (?, ?, ?, ?)",
            (product_id, filename, position, _now()),
        )
        return cur.lastrowid


def delete_image(image_id):
    with _connect() as conn:
        row = conn.execute("SELECT filename FROM product_images WHERE id = ?", (image_id,)).fetchone()
        conn.execute("DELETE FROM product_images WHERE id = ?", (image_id,))
        return row["filename"] if row else None
