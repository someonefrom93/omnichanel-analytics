"""GoldReader — read-only access to Gold star schema via DuckDB.

Mandatory merchant_id on every method enforces tenant isolation at the type system:
calling any read method without merchant_id raises TypeError.
"""

from __future__ import annotations

from typing import Any

import duckdb


class GoldReader:
    """Read-only accessor for Gold-layer data, tenant-fenced by merchant_id.

    Args:
        merchant_id: Default merchant for this reader instance.
            Every read method still REQUIRES merchant_id as a parameter.
        duckdb_path: Optional path to DuckDB database file.
            Defaults to ':memory:' for testing.
    """

    def __init__(
        self,
        *,
        merchant_id: str,
        duckdb_path: str = ":memory:",
    ) -> None:
        self._merchant_id = merchant_id
        self._conn = duckdb.connect(duckdb_path)

    def list_menu_items(self, *, merchant_id: str) -> list[dict[str, Any]]:
        """Return all menu items (line_item_sku, line_item_name) for a merchant.

        Args:
            merchant_id: REQUIRED. The merchant whose items to list.

        Returns:
            List of dicts with line_item_sku and line_item_name.
            Empty list if no items found or table does not exist.

        Raises:
            TypeError: If merchant_id is not provided as keyword argument.
        """
        try:
            rows = self._conn.execute(
                "SELECT line_item_sku, line_item_name "
                "FROM dim_menu_catalog "
                "WHERE merchant_id = ?",
                [merchant_id],
            ).fetchall()
        except duckdb.CatalogException:
            return []
        return [
            {"line_item_sku": row[0], "line_item_name": row[1]}
            for row in rows
        ]

    def list_merchant_cogs(self, *, merchant_id: str) -> list[dict[str, Any]]:
        """Return all COGS entries for a merchant from merchant_cogs table.

        Args:
            merchant_id: REQUIRED. The merchant whose COGS to list.

        Returns:
            List of dicts with line_item_sku, recipe_cost, packaging_cost.
            Empty list if no entries found or table does not exist.

        Raises:
            TypeError: If merchant_id is not provided as keyword argument.
        """
        try:
            rows = self._conn.execute(
                "SELECT line_item_sku, recipe_cost, packaging_cost "
                "FROM merchant_cogs "
                "WHERE merchant_id = ?",
                [merchant_id],
            ).fetchall()
        except duckdb.CatalogException:
            return []
        return [
            {
                "line_item_sku": row[0],
                "recipe_cost": float(row[1]),
                "packaging_cost": float(row[2]),
            }
            for row in rows
        ]
