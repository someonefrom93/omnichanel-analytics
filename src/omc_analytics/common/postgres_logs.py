"""PostgresLogs — LogsPort adapter using psycopg2 ThreadedConnectionPool.

# pragma: PR1 stub replaced by this real impl; InMemoryLogs remains the no-Postgres test path

Architecture:
    - connection_factory is injected — this class NEVER calls psycopg2.connect() directly
    - ThreadedConnectionPool is built from the factory in __init__
    - _acquire() context manager guarantees putconn in finally even on exception
    - All datetimes are naive UTC (pydantic RunLog model enforces this)

Error handling:
    - psycopg2.Error → PostgresLogsError (wrapped)
    - RunNotFoundError from update_finished rowcount=0 is re-raised as-is
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Literal

import psycopg2
import psycopg2.extensions
import psycopg2.pool

from omc_analytics.common.logs import RunLog

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PostgresLogsError(Exception):
    """Raised when a PostgresLogs SQL operation fails."""


# ---------------------------------------------------------------------------
# PostgresLogs implementation
# ---------------------------------------------------------------------------


class PostgresLogs:
    """LogsPort adapter backed by psycopg2 ThreadedConnectionPool.

    Args:
        connection_factory: A callable that returns a psycopg2 connection.
            The caller owns the DSN and connection arguments — this class
            NEVER calls psycopg2.connect() directly.
        min_conn: Minimum connections to seed the pool with (default 1).
        max_conn: Maximum connections in the pool (default 5).

    Example:
        factory = functools.partial(psycopg2.connect, dsn="postgresql://...")
        logs = PostgresLogs(connection_factory=factory)
    """

    def __init__(
        self,
        connection_factory: Callable[[], psycopg2.extensions.connection],
        min_conn: int = 1,
        max_conn: int = 5,
    ) -> None:
        self._factory = connection_factory
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            min_conn, max_conn, connection_factory=connection_factory
        )

    @contextmanager
    def _acquire(self) -> Generator[psycopg2.extensions.connection, None, None]:
        """Acquire a connection from the pool; guaranteed putconn in finally."""
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    def insert_started(self, row: RunLog) -> uuid.UUID:
        """Insert a STARTED row and return the run_id."""

        with self._acquire() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO pipeline_execution_logs "
                    "(id, merchant_id, run_id, pipeline_name, status, started_at, finished_at, error_class, error_message) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        str(row.id),
                        row.merchant_id,
                        str(row.run_id),
                        row.pipeline_name,
                        "STARTED",
                        row.started_at,
                        None,
                        None,
                        None,
                    ),
                )
                conn.commit()
                return row.run_id
            except psycopg2.Error as exc:
                raise PostgresLogsError(f"insert_started failed: {exc}") from exc

    def update_finished(
        self,
        run_id: uuid.UUID,
        status: Literal["SUCCESS", "FAILED"],
        error_class: str | None,
        error_message: str | None,
    ) -> None:
        """Update a row by run_id to SUCCESS or FAILED with optional error info."""
        from omc_analytics.common.logs import RunNotFoundError

        with self._acquire() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE pipeline_execution_logs "
                    "SET status = %s, finished_at = %s, error_class = %s, error_message = %s "
                    "WHERE run_id = %s",
                    (
                        status,
                        datetime.now(UTC),
                        error_class,
                        error_message,
                        str(run_id),
                    ),
                )
                if cursor.rowcount == 0:
                    raise RunNotFoundError(f"No run found with run_id={run_id}")
                conn.commit()
            except psycopg2.Error as exc:
                raise PostgresLogsError(f"update_finished failed: {exc}") from exc
