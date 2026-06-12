"""Unit tests for the merchant_cogs SQL DDL migration.

Applies the DDL against an in-memory SQLite database using the same
PostgreSQL-to-SQLite adapter pattern as test_migration_ddl.py.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# Test-only PostgreSQL → SQLite adapter (reused from migration_001 pattern)
# ---------------------------------------------------------------------------


def _adapt_postgres_to_sqlite(sql: str) -> str:
    """Translate PostgreSQL DDL to SQLite-compatible syntax."""

    lines = sql.splitlines()
    result_lines: list[str] = []
    for line in lines:
        upper = line.upper().strip()
        if upper.startswith("UNIQUE"):
            # Strip trailing comma from previous line, then skip this line
            if result_lines:
                prev = result_lines[-1].rstrip()
                if prev.endswith(","):
                    result_lines[-1] = prev[:-1]
            continue
        line = line.replace("UUID", "TEXT")
        line = line.replace("TIMESTAMPTZ", "TEXT")
        line = line.replace("DECIMAL(10,4)", "TEXT")
        line = line.replace("gen_random_uuid()", "(lower(hex(randomblob(16))))")
        line = line.replace("DEFAULT now()", "")
        # Clean up trailing spaces before comma from DEFAULT removal
        line = line.replace(" ,", ",")
        result_lines.append(line)
    return "\n".join(result_lines)


def _ddl_path() -> Path:
    return (
        Path(__file__).parent.parent.parent.parent
        / "src"
        / "omc_analytics"
        / "common"
        / "migrations"
        / "002_create_merchant_cogs.sql"
    )


def _load_ddl() -> str:
    return _ddl_path().read_text()


def _apply_ddl(conn: sqlite3.Connection) -> None:
    ddl = _load_ddl()
    adapted = _adapt_postgres_to_sqlite(ddl)
    conn.executescript(adapted)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ddl_002_file_exists_and_is_non_empty() -> None:
    path = _ddl_path()
    assert path.exists(), f"Migration file not found: {path}"
    assert path.stat().st_size > 0, "Migration file is empty"


def test_ddl_002_contains_create_table() -> None:
    adapted = _adapt_postgres_to_sqlite(_load_ddl())
    assert "CREATE TABLE" in adapted.upper(), "DDL missing CREATE TABLE"


def test_ddl_002_creates_table_with_6_columns() -> None:
    conn = sqlite3.connect(":memory:")
    _apply_ddl(conn)
    cursor = conn.execute("PRAGMA table_info(merchant_cogs)")
    columns = cursor.fetchall()
    assert len(columns) == 6, f"Expected 6 columns, got {len(columns)}: {columns}"
    names = [col[1] for col in columns]
    expected = [
        "id",
        "merchant_id",
        "line_item_sku",
        "recipe_cost",
        "packaging_cost",
        "updated_at",
    ]
    assert names == expected, f"Column names mismatch: {names}"


def test_ddl_002_idempotent() -> None:
    conn = sqlite3.connect(":memory:")
    _apply_ddl(conn)
    _apply_ddl(conn)  # second apply must not raise


def test_ddl_002_creates_unique_index() -> None:
    conn = sqlite3.connect(":memory:")
    _apply_ddl(conn)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='merchant_cogs'"
    )
    indexes = [
        row[0]
        for row in cursor.fetchall()
        if not row[0].startswith("sqlite_autoindex_")
    ]
    assert len(indexes) >= 1, f"Expected at least 1 explicit index, got {len(indexes)}"
    # The unique constraint becomes an autoindex in SQLite, but we also
    # create an explicit index idx_merchant_cogs_merchant
    index_names = [i.lower() for i in indexes]
    assert any(
        "merchant" in name for name in index_names
    ), f"No merchant index found in {index_names}"
