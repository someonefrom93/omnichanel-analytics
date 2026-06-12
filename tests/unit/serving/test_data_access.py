"""Unit tests for GoldReader — RED phase (tests before implementation)."""

from __future__ import annotations


class TestGoldReaderTenantFence:
    """Test that GoldReader enforces mandatory merchant_id."""

    def test_constructor_requires_merchant_id(self) -> None:
        """GIVEN no merchant_id
        WHEN GoldReader() called without merchant_id
        THEN TypeError is raised."""
        import pytest
        from omc_analytics.serving.data_access import GoldReader

        with pytest.raises(TypeError):
            GoldReader()  # type: ignore[call-arg]

    def test_list_menu_items_requires_merchant_id(self) -> None:
        """GIVEN GoldReader instantiated with merchant_id
        WHEN list_menu_items called without merchant_id arg
        THEN TypeError is raised."""
        import pytest
        from omc_analytics.serving.data_access import GoldReader

        reader = GoldReader(merchant_id="store_001")
        with pytest.raises(TypeError):
            reader.list_menu_items()  # type: ignore[call-arg]

    def test_list_merchant_cogs_requires_merchant_id(self) -> None:
        """GIVEN GoldReader instantiated with merchant_id
        WHEN list_merchant_cogs called without merchant_id arg
        THEN TypeError is raised."""
        import pytest
        from omc_analytics.serving.data_access import GoldReader

        reader = GoldReader(merchant_id="store_001")
        with pytest.raises(TypeError):
            reader.list_merchant_cogs()  # type: ignore[call-arg]


class TestGoldReaderMerchantScoping:
    """Test that GoldReader returns data scoped to the given merchant."""

    def test_list_menu_items_scoped_to_merchant(self) -> None:
        """GIVEN DuckDB with dim_menu_catalog rows for store_001 and store_002
        WHEN reader.list_menu_items(merchant_id="store_001") called
        THEN only store_001 rows are returned."""
        import duckdb
        from omc_analytics.serving.data_access import GoldReader

        conn = duckdb.connect(":memory:")
        conn.execute("""
            CREATE TABLE dim_menu_catalog AS
            SELECT 'store_001' AS merchant_id, 'BURGER' AS line_item_sku,
                   'Classic Burger' AS line_item_name
            UNION ALL
            SELECT 'store_001', 'FRIES', 'Medium Fries'
            UNION ALL
            SELECT 'store_002', 'PIZZA', 'Margherita'
        """)

        reader = GoldReader(merchant_id="store_001")
        # Override internal connection for testing
        reader._conn = conn  # type: ignore[attr-defined]

        rows = reader.list_menu_items(merchant_id="store_001")
        assert len(rows) == 2, f"Expected 2 rows for store_001, got {len(rows)}"
        skus = {row["line_item_sku"] for row in rows}  # type: ignore[index]
        assert skus == {"BURGER", "FRIES"}, f"Wrong SKUs: {skus}"

    def test_list_menu_items_empty_for_no_data(self) -> None:
        """GIVEN DuckDB with no rows for merchant
        WHEN list_menu_items called
        THEN empty list returned (not None, not error)."""
        import duckdb
        from omc_analytics.serving.data_access import GoldReader

        conn = duckdb.connect(":memory:")
        conn.execute("""
            CREATE TABLE dim_menu_catalog (
                merchant_id TEXT,
                line_item_sku TEXT,
                line_item_name TEXT
            )
        """)

        reader = GoldReader(merchant_id="store_001")
        reader._conn = conn  # type: ignore[attr-defined]

        rows = reader.list_menu_items(merchant_id="store_001")
        assert rows == [], f"Expected empty list, got {rows}"

    def test_list_merchant_cogs_scoped_to_merchant(self) -> None:
        """GIVEN DuckDB with merchant_cogs rows for store_001 and store_002
        WHEN reader.list_merchant_cogs(merchant_id="store_001") called
        THEN only store_001 rows are returned."""
        import duckdb
        from omc_analytics.serving.data_access import GoldReader

        conn = duckdb.connect(":memory:")
        conn.execute("""
            CREATE TABLE merchant_cogs AS
            SELECT 'store_001' AS merchant_id, 'BURGER' AS line_item_sku,
                   3.5 AS recipe_cost, 0.8 AS packaging_cost
            UNION ALL
            SELECT 'store_002', 'PIZZA', 5.0, 1.2
        """)

        reader = GoldReader(merchant_id="store_001")
        reader._conn = conn  # type: ignore[attr-defined]

        rows = reader.list_merchant_cogs(merchant_id="store_001")
        assert len(rows) == 1, f"Expected 1 row for store_001, got {len(rows)}"
        assert rows[0]["line_item_sku"] == "BURGER"  # type: ignore[index]
