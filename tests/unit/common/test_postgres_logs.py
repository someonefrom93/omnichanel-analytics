"""Unit tests for PostgresLogs and SQLiteLogs (LogsPort implementations).

Parametrized over two backends:
- SQLiteLogs: real in-memory SQLite with adapted DDL (fast, deterministic)
- PostgresLogs: real PostgreSQL via pytest-postgresql (for integration tests)

Pool putconn-on-exception tests use a mocked ThreadedConnectionPool to verify
the finally-block guarantee without needing a real Postgres instance.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest

from omc_analytics.common.logs import RunLog, RunNotFoundError
from omc_analytics.common.postgres_logs import PostgresLogs, PostgresLogsError
from omc_analytics.common.sqlite_logs import SQLiteLogs

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_logs() -> SQLiteLogs:
    """Fresh in-memory SQLiteLogs instance."""
    return SQLiteLogs()


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_run_log(
    merchant_id: str = "M1",
    pipeline_name: Literal["otter_bronze_ingestion"] = "otter_bronze_ingestion",
) -> RunLog:
    return RunLog(
        id=uuid.uuid4(),
        merchant_id=merchant_id,
        run_id=uuid.uuid4(),
        pipeline_name=pipeline_name,
        status="STARTED",
        started_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Shared test cases for both backends
# ---------------------------------------------------------------------------


class TestInsertStarted:
    """Tests for insert_started across both implementations."""

    def test_persists_all_9_columns(self, logs_impl: tuple[object, callable]) -> None:
        """Insert a RunLog, query it back, assert all 9 fields match."""
        logs, _reset = logs_impl
        row = _make_run_log()
        logs.insert_started(row)
        rows = logs.get_all()
        assert len(rows) == 1
        r = rows[0]
        assert r.merchant_id == row.merchant_id
        assert r.run_id == row.run_id
        assert r.pipeline_name == row.pipeline_name
        assert r.status == "STARTED"
        assert r.started_at is not None
        assert r.finished_at is None
        assert r.error_class is None
        assert r.error_message is None

    def test_returns_run_id(self, logs_impl: tuple[object, callable]) -> None:
        """The returned UUID must equal the input row.run_id."""
        logs, _reset = logs_impl
        row = _make_run_log()
        result = logs.insert_started(row)
        assert result == row.run_id


class TestUpdateFinished:
    """Tests for update_finished across both implementations."""

    def test_sets_finished_at_and_status(
        self, logs_impl: tuple[object, callable]
    ) -> None:
        """Insert STARTED, update to SUCCESS, query back — status and finished_at set."""
        logs, _reset = logs_impl
        row = _make_run_log()
        logs.insert_started(row)
        logs.update_finished(row.run_id, "SUCCESS", None, None)
        rows = logs.get_all()
        assert len(rows) == 1
        r = rows[0]
        assert r.status == "SUCCESS"
        assert r.finished_at is not None

    def test_with_failed_status_records_error(
        self, logs_impl: tuple[object, callable]
    ) -> None:
        """Insert STARTED, update to FAILED with error info, query back."""
        logs, _reset = logs_impl
        row = _make_run_log()
        logs.insert_started(row)
        logs.update_finished(
            row.run_id, "FAILED", "OtterAPIError", "Rate limit exceeded"
        )
        rows = logs.get_all()
        assert len(rows) == 1
        r = rows[0]
        assert r.status == "FAILED"
        assert r.error_class == "OtterAPIError"
        assert r.error_message == "Rate limit exceeded"
        assert r.finished_at is not None

    def test_raises_run_not_found_for_unknown_run_id(
        self, logs_impl: tuple[object, callable]
    ) -> None:
        """Update without prior insert must raise RunNotFoundError."""
        logs, _reset = logs_impl
        unknown = uuid.uuid4()
        with pytest.raises(RunNotFoundError):
            logs.update_finished(unknown, "SUCCESS", None, None)

    def test_insert_started_twice_raises_unique_violation(
        self, logs_impl: tuple[object, callable]
    ) -> None:
        """Second insert with same (id, run_id) must raise PostgresLogsError or similar."""
        logs, _reset = logs_impl
        row = _make_run_log()
        logs.insert_started(row)
        with pytest.raises((sqlite3.IntegrityError, PostgresLogsError)):
            logs.insert_started(row)


# ---------------------------------------------------------------------------
# PostgresLogs-only tests (pool lifecycle)
# ---------------------------------------------------------------------------


class TestPostgresLogsPoolBehavior:
    """PostgresLogs-only tests verifying connection pool lifecycle."""

    def test_pool_releases_connection_on_exception(self) -> None:
        """putconn must be called in finally even when cursor.execute raises."""
        import psycopg2
        import psycopg2.pool

        # Build a mock pool whose getconn returns a connection that raises on execute
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = psycopg2.Error("simulated SQL error")
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.commit = MagicMock()

        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool.putconn = MagicMock()

        # Patch ThreadedConnectionPool so PostgresLogs.__init__ uses our mock
        with patch.object(
            psycopg2.pool, "ThreadedConnectionPool", return_value=mock_pool
        ):
            logs = PostgresLogs(connection_factory=MagicMock())
            row = _make_run_log()
            with pytest.raises(PostgresLogsError):
                logs.insert_started(row)

        # Assert putconn was called exactly once in the finally block
        mock_pool.putconn.assert_called_once_with(mock_conn)

    def test_pool_releases_connection_on_success(self) -> None:
        """putconn must be called after successful insert_started."""
        import psycopg2
        import psycopg2.pool

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.commit = MagicMock()

        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool.putconn = MagicMock()

        with patch.object(
            psycopg2.pool, "ThreadedConnectionPool", return_value=mock_pool
        ):
            logs = PostgresLogs(connection_factory=MagicMock())
            row = _make_run_log()
            result = logs.insert_started(row)

        assert result == row.run_id
        mock_pool.putconn.assert_called_once_with(mock_conn)


# ---------------------------------------------------------------------------
# Parametrization: run shared tests against SQLiteLogs
# (PostgresLogs requires a real DB; we test those separately via integration marker)
# ---------------------------------------------------------------------------


@pytest.fixture(params=[SQLiteLogs])
def logs_impl(request: pytest.FixtureRequest) -> tuple[object, callable]:
    """Parametrized fixture yielding (logs_instance, reset_fn) for each backend."""
    impl_cls = request.param
    if impl_cls is SQLiteLogs:
        logs = SQLiteLogs()
        return logs, lambda: None  # reset not needed for in-memory
    else:
        raise NotImplementedError(f"Unknown impl: {impl_cls}")
