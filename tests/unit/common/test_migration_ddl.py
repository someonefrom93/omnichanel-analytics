"""Unit tests for the pipeline_execution_logs SQL DDL migration.

Applies the DDL against an in-memory SQLite database using a small
PostgreSQL-to-SQLite adapter (test-only, not for production use).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# Test-only PostgreSQL → SQLite adapter
# ---------------------------------------------------------------------------


def _adapt_postgres_to_sqlite(sql: str) -> str:
    """Translate PostgreSQL DDL to SQLite-compatible syntax.

    Rules:
    - UUID → TEXT (SQLite has no native UUID type)
    - TIMESTAMPTZ → TEXT (store as ISO-8601 UTC strings)
    - BYTEA → BLOB (SQLite uses BLOB for binary data)
    - CHECK constraints → stripped (SQLite handles them differently)
    - CREATE INDEX → kept as-is (SQLite supports CREATE INDEX)
    - IF NOT EXISTS → kept (supported by both)
    """

    def _strip_check_constraint(line: str) -> str:
        """Remove CHECK (expression) clause from a column-def line, preserving the column separator comma.

        Handles nested parentheses inside the CHECK expression by counting depth.
        """
        upper = line.upper()
        idx = upper.find("CHECK")
        if idx == -1:
            return line

        # Find the opening '(' after CHECK (skip any whitespace)
        i = idx + 5
        while i < len(line) and line[i] in " \t":
            i += 1
        if i >= len(line) or line[i] != "(":
            return line  # malformed, leave unchanged

        depth = 0
        while i < len(line):
            ch = line[i]
            if ch == "(":
                depth += 1
                i += 1
            elif ch == ")":
                # Closing paren found
                if depth == 1:
                    # This is the matching ')' for the CHECK opening '('
                    break
                depth -= 1
                i += 1
            else:
                i += 1

        # i now points to the closing ')' of the CHECK clause
        # After ')' there may be a comma (column separator)
        rest = line[i + 1 :]  # everything after the closing ')'
        after_paren = rest.lstrip()
        if after_paren.startswith(","):
            # Comma present — keep it as column separator
            return line[:idx].rstrip() + ","
        else:
            return line[:idx].rstrip()

    lines = sql.splitlines()
    result_lines: list[str] = []
    for line in lines:
        line = _strip_check_constraint(line)
        line = line.replace("UUID", "TEXT")
        line = line.replace("TIMESTAMPTZ", "TEXT")
        line = line.replace("BYTEA", "BLOB")
        result_lines.append(line)
    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ddl_path() -> Path:
    """Return the path to the DDL migration file."""
    return (
        Path(__file__).parent.parent.parent.parent
        / "src"
        / "omc_analytics"
        / "common"
        / "migrations"
        / "001_create_pipeline_execution_logs.sql"
    )


def _load_ddl() -> str:
    """Load the raw DDL text from the migration file."""
    return _ddl_path().read_text()


def _apply_ddl(conn: sqlite3.Connection) -> None:
    """Apply the DDL to an in-memory SQLite database."""
    ddl = _load_ddl()
    adapted = _adapt_postgres_to_sqlite(ddl)
    conn.executescript(adapted)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_ddl_file_exists_and_is_non_empty() -> None:
    """The migration file must exist and contain bytes."""
    path = _ddl_path()
    assert path.exists(), f"Migration file not found: {path}"
    assert path.stat().st_size > 0, "Migration file is empty"


def test_ddl_contains_create_table_statement() -> None:
    """Adapted SQL must contain a CREATE TABLE statement."""
    adapted = _adapt_postgres_to_sqlite(_load_ddl())
    assert "CREATE TABLE" in adapted.upper(), "DDL missing CREATE TABLE"


def test_ddl_creates_table_with_9_columns() -> None:
    """Applying the DDL must create pipeline_execution_logs with 9 columns."""
    conn = sqlite3.connect(":memory:")
    _apply_ddl(conn)
    cursor = conn.execute("PRAGMA table_info(pipeline_execution_logs)")
    columns = cursor.fetchall()
    assert len(columns) == 9, f"Expected 9 columns, got {len(columns)}: {columns}"
    names = [col[1] for col in columns]
    expected = [
        "id",
        "merchant_id",
        "run_id",
        "pipeline_name",
        "status",
        "started_at",
        "finished_at",
        "error_class",
        "error_message",
    ]
    assert names == expected, f"Column names mismatch: {names}"


def test_ddl_idempotent() -> None:
    """Applying the DDL twice must not raise (IF NOT EXISTS semantics)."""
    conn = sqlite3.connect(":memory:")
    _apply_ddl(conn)  # first apply
    _apply_ddl(conn)  # second apply — must not raise


def test_ddl_column_types_match_design() -> None:
    """All columns must be TEXT after adaptation (SQLite compatibility)."""
    conn = sqlite3.connect(":memory:")
    _apply_ddl(conn)
    cursor = conn.execute("PRAGMA table_info(pipeline_execution_logs)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    # All 9 columns map to TEXT in our SQLite adapter
    text_cols = [
        "id",
        "merchant_id",
        "run_id",
        "pipeline_name",
        "status",
        "started_at",
        "finished_at",
        "error_class",
        "error_message",
    ]
    for col in text_cols:
        assert col in columns, f"Missing column: {col}"
        assert (
            columns[col] == "TEXT"
        ), f"Column {col} has type {columns[col]}, expected TEXT"


def test_ddl_creates_two_indexes() -> None:
    """Two user-created indexes must exist on pipeline_execution_logs after DDL apply.

    SQLite auto-creates an index for PRIMARY KEY (sqlite_autoindex_*), so we
    filter those out and assert only the 2 explicit indexes are present.
    """
    conn = sqlite3.connect(":memory:")
    _apply_ddl(conn)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='pipeline_execution_logs'"
    )
    indexes = [
        row[0]
        for row in cursor.fetchall()
        if not row[0].startswith("sqlite_autoindex_")
    ]
    assert (
        len(indexes) == 2
    ), f"Expected 2 explicit indexes, got {len(indexes)}: {indexes}"
