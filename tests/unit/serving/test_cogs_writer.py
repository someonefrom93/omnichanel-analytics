"""Unit tests for CogsWriter — RED phase (tests before implementation)."""

from __future__ import annotations

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# CogsWriter import — will fail until we create the module (RED)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def postgres_container():
    """Start a testcontainers PostgreSQL instance for integration tests."""
    with PostgresContainer("postgres:14") as postgres:
        yield postgres


@pytest.fixture
def dsn(postgres_container: PostgresContainer) -> str:
    """Return the DSN pointing at the test container."""
    return postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )


@pytest.fixture
def setup_table(dsn: str):
    """Create the merchant_cogs table before each test."""
    conn = psycopg2.connect(dsn)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS merchant_cogs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            merchant_id     TEXT NOT NULL,
            line_item_sku   TEXT NOT NULL,
            recipe_cost     DECIMAL(10,4) NOT NULL DEFAULT 0,
            packaging_cost  DECIMAL(10,4) NOT NULL DEFAULT 0,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (merchant_id, line_item_sku)
        )
    """
    )
    conn.commit()
    cursor.close()
    conn.close()
    yield
    # Cleanup
    conn = psycopg2.connect(dsn)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM merchant_cogs")
    conn.commit()
    cursor.close()
    conn.close()


# ---------------------------------------------------------------------------
# RED tests — CogsWriter does not exist yet, these MUST fail on import
# ---------------------------------------------------------------------------


class TestCogsWriterUpsert:
    """Test CogsWriter.upsert behavior."""

    def test_upsert_inserts_new_row(
        self,
        dsn: str,
        setup_table: None,
    ) -> None:
        """GIVEN empty merchant_cogs table
        WHEN writer.upsert("store_001", "BURGER", 3.50, 0.80) called
        THEN row exists with correct values."""
        from omc_analytics.serving.cogs_writer import CogsWriter

        writer = CogsWriter(dsn=dsn)
        writer.upsert(
            merchant_id="store_001",
            line_item_sku="BURGER",
            recipe_cost=3.50,
            packaging_cost=0.80,
        )

        conn = psycopg2.connect(dsn)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT recipe_cost, packaging_cost FROM merchant_cogs "
            "WHERE merchant_id=%s AND line_item_sku=%s",
            ("store_001", "BURGER"),
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        assert row is not None, "Row was not inserted"
        assert float(row[0]) == 3.50, f"Expected recipe_cost=3.50, got {row[0]}"
        assert float(row[1]) == 0.80, f"Expected packaging_cost=0.80, got {row[1]}"

    def test_upsert_updates_existing_row(
        self,
        dsn: str,
        setup_table: None,
    ) -> None:
        """GIVEN existing row for ("store_001", "BURGER") with recipe_cost=3.50
        WHEN writer.upsert("store_001", "BURGER", 4.20, 0.90) called
        THEN row updated to new values."""
        from omc_analytics.serving.cogs_writer import CogsWriter

        writer = CogsWriter(dsn=dsn)

        # Insert initial row
        writer.upsert("store_001", "BURGER", 3.50, 0.80)

        # Update
        writer.upsert("store_001", "BURGER", 4.20, 0.90)

        conn = psycopg2.connect(dsn)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT recipe_cost, packaging_cost FROM merchant_cogs "
            "WHERE merchant_id=%s AND line_item_sku=%s",
            ("store_001", "BURGER"),
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        assert row is not None
        assert float(row[0]) == 4.20, f"Expected recipe_cost=4.20, got {row[0]}"
        assert float(row[1]) == 0.90, f"Expected packaging_cost=0.90, got {row[1]}"

    def test_upsert_preserves_merchant_isolation(
        self,
        dsn: str,
        setup_table: None,
    ) -> None:
        """GIVEN rows for store_001 and store_002
        WHEN upsert updates only store_001 row
        THEN store_002 row is unchanged (merchant isolation)."""
        from omc_analytics.serving.cogs_writer import CogsWriter

        writer = CogsWriter(dsn=dsn)
        writer.upsert("store_001", "BURGER", 3.50, 0.80)
        writer.upsert("store_002", "FRIES", 1.50, 0.30)

        # Update only store_001
        writer.upsert("store_001", "BURGER", 4.20, 0.90)

        conn = psycopg2.connect(dsn)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT recipe_cost FROM merchant_cogs "
            "WHERE merchant_id=%s AND line_item_sku=%s",
            ("store_002", "FRIES"),
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        assert row is not None
        assert float(row[0]) == 1.50, "store_002 row was modified — isolation broken"


class TestCogsWriterDelete:
    """Test CogsWriter.delete behavior."""

    def test_delete_removes_row(
        self,
        dsn: str,
        setup_table: None,
    ) -> None:
        """GIVEN a row for ("store_001", "BURGER")
        WHEN writer.delete("store_001", "BURGER") called
        THEN row is removed."""
        from omc_analytics.serving.cogs_writer import CogsWriter

        writer = CogsWriter(dsn=dsn)
        writer.upsert("store_001", "BURGER", 3.50, 0.80)
        writer.delete("store_001", "BURGER")

        conn = psycopg2.connect(dsn)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM merchant_cogs "
            "WHERE merchant_id=%s AND line_item_sku=%s",
            ("store_001", "BURGER"),
        )
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        assert count == 0, f"Row was not deleted, count={count}"

    def test_delete_nonexistent_no_error(
        self,
        dsn: str,
        setup_table: None,
    ) -> None:
        """GIVEN empty table, WHEN delete nonexistent row, THEN no error raised."""
        from omc_analytics.serving.cogs_writer import CogsWriter

        writer = CogsWriter(dsn=dsn)
        # Must not raise
        writer.delete("store_001", "NONEXISTENT")
        # Must not raise
        writer.delete("store_001", "NONEXISTENT")
