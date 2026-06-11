"""LogsPort Protocol and InMemoryLogs stub — PR1 in-memory implementation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel


class RunLog(BaseModel):
    """Pydantic model for pipeline execution log rows.

    Schema matches the 9-column locked decision from design.md.
    PR1 uses in-memory list storage.  # pragma: PR2 swap to Postgres-backed impl
    """

    id: UUID
    merchant_id: str
    run_id: UUID
    pipeline_name: Literal["otter_bronze_ingestion"]
    status: Literal["STARTED", "SUCCESS", "FAILED"]
    started_at: datetime
    finished_at: datetime | None = None
    error_class: str | None = None
    error_message: str | None = None


class LogsPort(Protocol):
    """Protocol for inserting and updating pipeline execution log rows."""

    def insert_started(self, row: RunLog) -> UUID:
        """Insert a STARTED row and return the run_id."""
        ...

    def update_finished(
        self,
        run_id: UUID,
        status: Literal["SUCCESS", "FAILED"],
        error_class: str | None,
        error_message: str | None,
    ) -> None:
        """Update a row by run_id to SUCCESS or FAILED with optional error info."""
        ...


class RunNotFoundError(LookupError):
    """Raised when a run_id is not found in the log store."""


class InMemoryLogs:
    """PR1 stub for LogsPort — append-only list, no Postgres."""

    def __init__(self) -> None:
        self._rows: list[RunLog] = []

    def insert_started(self, row: RunLog) -> UUID:
        self._rows.append(row)
        return row.run_id

    def update_finished(
        self,
        run_id: UUID,
        status: Literal["SUCCESS", "FAILED"],
        error_class: str | None,
        error_message: str | None,
    ) -> None:
        for row in self._rows:
            if row.run_id == run_id:
                row.finished_at = datetime.now(tz=__import__("datetime").timezone.utc)
                row.status = status
                row.error_class = error_class
                row.error_message = error_message
                return
        raise RunNotFoundError(f"No run found with run_id={run_id}")

    def get_all(self) -> list[RunLog]:
        """Return all rows in insertion order."""
        return self._rows.copy()
