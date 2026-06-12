"""CogsWriter — COGS upsert/delete adapter using psycopg2 ThreadedConnectionPool.

Mirrors the PostgresLogs pattern: pool acquired via _acquire context manager.
Accepts a DSN string directly (not connection_factory) for simpler pool creation.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime

import psycopg2
import psycopg2.extensions
import psycopg2.pool


class CogsWriter:
    """psycopg2-backed writer for merchant_cogs table.

    Args:
        dsn: PostgreSQL connection string (e.g. "postgresql://user:pass@host/db").
        min_conn: Minimum connections in pool (default 0 — lazy).
        max_conn: Maximum connections in pool (default 5).
    """

    def __init__(
        self,
        dsn: str,
        min_conn: int = 0,
        max_conn: int = 5,
    ) -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            min_conn, max_conn, dsn
        )

    @contextmanager
    def _acquire(self) -> Generator[psycopg2.extensions.connection, None, None]:
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    def upsert(
        self,
        merchant_id: str,
        line_item_sku: str,
        recipe_cost: float,
        packaging_cost: float,
    ) -> None:
        """Insert or update a row in merchant_cogs.

        Uses INSERT ... ON CONFLICT DO UPDATE for idempotent upsert.
        """
        with self._acquire() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO merchant_cogs "
                "(merchant_id, line_item_sku, recipe_cost, packaging_cost, updated_at) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (merchant_id, line_item_sku) "
                "DO UPDATE SET recipe_cost = EXCLUDED.recipe_cost, "
                "packaging_cost = EXCLUDED.packaging_cost, "
                "updated_at = EXCLUDED.updated_at",
                (merchant_id, line_item_sku, recipe_cost, packaging_cost, datetime.now(UTC)),
            )
            conn.commit()

    def delete(self, merchant_id: str, line_item_sku: str) -> None:
        """Delete a row from merchant_cogs by merchant_id and line_item_sku."""
        with self._acquire() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM merchant_cogs "
                "WHERE merchant_id = %s AND line_item_sku = %s",
                (merchant_id, line_item_sku),
            )
            conn.commit()
