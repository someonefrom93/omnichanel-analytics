"""PostgresAlerts — AlertsPort adapter using psycopg2 ThreadedConnectionPool.

Architecture mirrors PostgresLogs exactly:
    - connection_factory injected (never calls psycopg2.connect directly)
    - ThreadedConnectionPool built from factory
    - _acquire() context manager guarantees putconn in finally
    - All datetimes are UTC
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager

import psycopg2
import psycopg2.extensions
import psycopg2.pool

from omc_analytics.common.alerts import EngineeringAlert


class PostgresAlertsError(Exception):
    """Raised when a PostgresAlerts SQL operation fails."""


class PostgresAlerts:
    """AlertsPort adapter backed by psycopg2 ThreadedConnectionPool.

    Args:
        connection_factory: A callable returning a psycopg2 connection.
        min_conn: Minimum connections (default 0 — lazy creation).
        max_conn: Maximum connections (default 5).
    """

    def __init__(
        self,
        connection_factory: Callable[[], psycopg2.extensions.connection],
        min_conn: int = 0,
        max_conn: int = 5,
    ) -> None:
        self._factory = connection_factory
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            min_conn, max_conn, connection_factory=connection_factory
        )

    @contextmanager
    def _acquire(self) -> Generator[psycopg2.extensions.connection, None, None]:
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    def insert_alert(self, alert: EngineeringAlert) -> uuid.UUID:
        """Insert an alert row and return its UUID."""
        with self._acquire() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO engineering_alerts "
                    "(id, source, severity, error_class, error_message, stack_trace, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        str(alert.id),
                        alert.source,
                        alert.severity,
                        alert.error_class,
                        alert.error_message,
                        alert.stack_trace,
                        alert.created_at,
                    ),
                )
                conn.commit()
                return alert.id
            except psycopg2.Error as exc:
                raise PostgresAlertsError(f"insert_alert failed: {exc}") from exc
