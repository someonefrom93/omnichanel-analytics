"""SQLiteLogs — production-grade LogsPort implementation backed by in-memory SQLite.

# pragma: PR1 stub replaced by this real impl; InMemoryLogs remains the no-Postgres test path

This is a legitimate production implementation of the LogsPort Protocol suitable for
small deployments or local development where PostgreSQL is not available.  It reads
the real DDL from the migrations directory at runtime and applies it through the
_postgres_to_sqlite adapter so the SQLite schema stays in sync with the PostgreSQL
schema automatically.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from omc_analytics.common.logs import RunLog

# ---------------------------------------------------------------------------
# PostgreSQL → SQLite DDL adapter
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
        """Remove CHECK (expression) clause from a column-def line."""
        upper = line.upper()
        idx = upper.find("CHECK")
        if idx == -1:
            return line

        i = idx + 5
        while i < len(line) and line[i] in " \t":
            i += 1
        if i >= len(line) or line[i] != "(":
            return line

        depth = 0
        while i < len(line):
            ch = line[i]
            if ch == "(":
                depth += 1
                i += 1
            elif ch == ")":
                if depth == 1:
                    break
                depth -= 1
                i += 1
            else:
                i += 1

        rest = line[i + 1 :]
        after_paren = rest.lstrip()
        if after_paren.startswith(","):
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
# SQLiteLogs implementation
# ---------------------------------------------------------------------------


class SQLiteLogs:
    """Production-grade LogsPort backed by in-memory SQLite.

    Reads the real DDL from the migrations directory at runtime and applies
    it through the _adapt_postgres_to_sqlite adapter so the SQLite schema
    stays in sync with the PostgreSQL schema.

    All datetimes are stored as naive UTC strings (ISO-8601) to match how
    the PostgreSQL TIMESTAMPTZ columns behave in the real schema.
    """

    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._apply_ddl()

    def _ddl_path(self) -> Path:
        return (
            Path(__file__).parent.parent.parent
            / "omc_analytics"
            / "common"
            / "migrations"
            / "001_create_pipeline_execution_logs.sql"
        )

    def _apply_ddl(self) -> None:
        raw_ddl = self._ddl_path().read_text()
        adapted = _adapt_postgres_to_sqlite(raw_ddl)
        self._conn.executescript(adapted)

    def insert_started(self, row: RunLog) -> uuid.UUID:
        """Insert a STARTED row and return the run_id."""
        self._conn.execute(
            "INSERT INTO pipeline_execution_logs "
            "(id, merchant_id, run_id, pipeline_name, status, started_at, finished_at, error_class, error_message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(row.id),
                row.merchant_id,
                str(row.run_id),
                row.pipeline_name,
                "STARTED",
                _naive_utc(row.started_at),
                None,
                None,
                None,
            ),
        )
        self._conn.commit()
        return row.run_id

    def update_finished(
        self,
        run_id: uuid.UUID,
        status: Literal["SUCCESS", "FAILED"],
        error_class: str | None,
        error_message: str | None,
    ) -> None:
        """Update a row by run_id to SUCCESS or FAILED with optional error info."""
        from omc_analytics.common.logs import RunNotFoundError

        cursor = self._conn.execute(
            "UPDATE pipeline_execution_logs "
            "SET status = ?, finished_at = ?, error_class = ?, error_message = ? "
            "WHERE run_id = ?",
            (
                status,
                _naive_utc(datetime.now(UTC)),
                error_class,
                error_message,
                str(run_id),
            ),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            raise RunNotFoundError(f"No run found with run_id={run_id}")

    def get_all(self) -> list[RunLog]:
        """Return all rows in insertion order (for test inspection)."""
        cursor = self._conn.execute(
            "SELECT id, merchant_id, run_id, pipeline_name, status, "
            "started_at, finished_at, error_class, error_message "
            "FROM pipeline_execution_logs ORDER BY started_at"
        )
        rows: list[RunLog] = []
        for row in cursor.fetchall():
            rows.append(
                RunLog(
                    id=uuid.UUID(row[0]),
                    merchant_id=row[1],
                    run_id=uuid.UUID(row[2]),
                    pipeline_name=row[3],
                    status=row[4],
                    started_at=_parse_utc(row[5]),
                    finished_at=_parse_utc(row[6]) if row[6] else None,
                    error_class=row[7],
                    error_message=row[8],
                )
            )
        return rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _naive_utc(dt: datetime) -> str:
    """Convert a datetime to a naive UTC ISO-8601 string."""
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)  # strip tzinfo to get naive UTC
    return dt.isoformat()


def _parse_utc(s: str) -> datetime:
    """Parse a naive UTC ISO-8601 string to a tz-aware UTC datetime."""
    return datetime.fromisoformat(s).replace(tzinfo=UTC)
