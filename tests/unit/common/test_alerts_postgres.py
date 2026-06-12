"""Tests for DDL 003 + PostgresAlerts (PR6a)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from omc_analytics.common.alerts import EngineeringAlert

# ---------------------------------------------------------------------------
# SQLite adapter (same pattern as test_migration_ddl.py)
# ---------------------------------------------------------------------------


def _adapt_postgres_to_sqlite(sql: str) -> str:
    """Translate PostgreSQL DDL to SQLite-compatible syntax."""
    lines = sql.splitlines()
    result_lines: list[str] = []
    for line in lines:
        upper = line.upper()
        idx = upper.find("CHECK")
        if idx != -1:
            i = idx + 5
            while i < len(line) and line[i] in " \t":
                i += 1
            if i < len(line) and line[i] == "(":
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
                rest = line[i + 1:].lstrip()
                if rest.startswith(","):
                    line = line[:idx].rstrip() + ","
                else:
                    line = line[:idx].rstrip()
        line = line.replace("UUID", "TEXT")
        line = line.replace("TIMESTAMPTZ", "TEXT")
        result_lines.append(line)
    return "\n".join(result_lines)


def _ddl_003_path() -> Path:
    return (
        Path(__file__).parent.parent.parent.parent
        / "src" / "omc_analytics" / "common" / "migrations"
        / "003_create_engineering_alerts.sql"
    )


def _load_ddl_003() -> str:
    return _ddl_003_path().read_text()


def _apply_ddl_003(conn: sqlite3.Connection) -> None:
    ddl = _load_ddl_003()
    adapted = _adapt_postgres_to_sqlite(ddl)
    conn.executescript(adapted)


# ---------------------------------------------------------------------------
# DDL 003 tests (SQLite in-memory)
# ---------------------------------------------------------------------------


class TestDDL003:
    """Tests for 003_create_engineering_alerts.sql."""

    def test_ddl_file_exists(self):
        assert _ddl_003_path().exists()
        assert _ddl_003_path().stat().st_size > 0

    def test_ddl_creates_7_columns(self):
        conn = sqlite3.connect(":memory:")
        _apply_ddl_003(conn)
        cursor = conn.execute("PRAGMA table_info(engineering_alerts)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        assert len(columns) == 7
        for name in ("id", "source", "severity", "error_class",
                     "error_message", "stack_trace", "created_at"):
            assert name in columns

    def test_ddl_idempotent(self):
        conn = sqlite3.connect(":memory:")
        _apply_ddl_003(conn)
        _apply_ddl_003(conn)  # must not raise

    def test_ddl_creates_index(self):
        conn = sqlite3.connect(":memory:")
        _apply_ddl_003(conn)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='engineering_alerts'"
        )
        indexes = [
            row[0] for row in cursor.fetchall()
            if not row[0].startswith("sqlite_autoindex_")
        ]
        assert len(indexes) == 1


# ---------------------------------------------------------------------------
# PostgresAlerts integration tests (requires Docker)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPostgresAlertsIntegration:
    """Tests for PostgresAlerts using testcontainers (requires Docker)."""

    @pytest.fixture(scope="class")
    def pg_url(self):
        """Start a PostgreSQL container, apply DDL 003, return connection URL."""
        from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
        import psycopg2

        container = PostgresContainer("postgres:14")
        container.start()
        ddl_url = container.get_connection_url()

        conn = psycopg2.connect(ddl_url)
        ddl = _load_ddl_003()
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
        conn.close()

        yield ddl_url
        container.stop()

    @pytest.fixture
    def alerts(self, pg_url):
        """Build PostgresAlerts with connection factory."""
        import functools
        import psycopg2
        from omc_analytics.common.postgres_alerts import PostgresAlerts

        factory = functools.partial(psycopg2.connect, pg_url)
        return PostgresAlerts(connection_factory=factory)

    def test_insert_alert_round_trip(self, alerts):
        alert = EngineeringAlert(
            id=uuid.uuid4(),
            source="otter_client",
            severity="error",
            error_class="Tier2LatencyError",
            error_message="Server error 503: Service Unavailable",
            stack_trace="Traceback (most recent call last):\n  ...",
            created_at=datetime.now(UTC),
        )
        result = alerts.insert_alert(alert)
        assert result == alert.id

    def test_insert_and_query_by_severity(self, alerts, pg_url):
        import psycopg2

        alert = EngineeringAlert(
            id=uuid.uuid4(),
            source="bronze_ingestion",
            severity="critical",
            error_class="ValueError",
            error_message="Missing data key",
            created_at=datetime.now(UTC),
        )
        alerts.insert_alert(alert)

        conn = psycopg2.connect(pg_url)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM engineering_alerts WHERE severity = %s",
                ("critical",),
            )
            rows = cur.fetchall()
            assert len(rows) == 1
            assert rows[0][2] == "critical"
        conn.close()
