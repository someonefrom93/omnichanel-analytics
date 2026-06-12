"""AlertsPort Protocol and EngineeringAlert model — PR6a.

Architecture mirrors LogsPort/PostgresLogs:
    - AlertsPort Protocol defines the contract
    - EngineeringAlert is a Pydantic model
    - InMemoryAlerts is the list-backed dev/test path
    - PostgresAlerts is the psycopg2-pool-backed production path
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel


class EngineeringAlert(BaseModel):
    """Pydantic model for an engineering alert row."""

    id: UUID
    source: str
    severity: str
    error_class: str
    error_message: str
    stack_trace: str | None = None
    created_at: datetime


class AlertsPort(Protocol):
    """Protocol for inserting engineering alerts."""

    def insert_alert(self, alert: EngineeringAlert) -> UUID:
        """Insert an alert and return its UUID."""
        ...


class InMemoryAlerts:
    """PR6a stub for AlertsPort — append-only list, mirrors InMemoryLogs."""

    def __init__(self) -> None:
        self._alerts: list[EngineeringAlert] = []

    def insert_alert(self, alert: EngineeringAlert) -> UUID:
        self._alerts.append(alert)
        return alert.id

    def get_all(self) -> list[EngineeringAlert]:
        """Return all alerts in insertion order."""
        return self._alerts.copy()
