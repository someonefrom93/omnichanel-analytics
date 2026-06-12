"""Tests for AlertsPort Protocol and InMemoryAlerts (PR6a)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from omc_analytics.common.alerts import EngineeringAlert, InMemoryAlerts


class TestEngineeringAlertModel:
    """Validation tests for EngineeringAlert Pydantic model."""

    def test_valid_alert_round_trip(self):
        alert_id = uuid4()
        now = datetime.now(UTC)
        alert = EngineeringAlert(
            id=alert_id,
            source="otter_client",
            severity="error",
            error_class="Tier2LatencyError",
            error_message="Server error 502: Bad Gateway",
            stack_trace=None,
            created_at=now,
        )
        assert alert.id == alert_id
        assert alert.source == "otter_client"
        assert alert.severity == "error"
        assert alert.error_class == "Tier2LatencyError"
        assert alert.error_message == "Server error 502: Bad Gateway"
        assert alert.stack_trace is None
        assert alert.created_at == now

    def test_alert_with_stack_trace(self):
        alert = EngineeringAlert(
            id=uuid4(),
            source="bronze_ingestion",
            severity="critical",
            error_class="KeyError",
            error_message="Missing key 'orders'",
            stack_trace="Traceback (most recent call last):\n  File ...",
            created_at=datetime.now(UTC),
        )
        assert alert.stack_trace == "Traceback (most recent call last):\n  File ..."


class TestInMemoryAlerts:
    """Tests for InMemoryAlerts (list-backed, mirrors InMemoryLogs)."""

    def test_insert_returns_uuid(self):
        alerts = InMemoryAlerts()
        alert = EngineeringAlert(
            id=uuid4(),
            source="test",
            severity="warning",
            error_class="TestError",
            error_message="test message",
            created_at=datetime.now(UTC),
        )
        result = alerts.insert_alert(alert)
        assert result == alert.id

    def test_inserted_alert_is_retrievable(self):
        alerts = InMemoryAlerts()
        alert = EngineeringAlert(
            id=uuid4(),
            source="otter_client",
            severity="error",
            error_class="Tier1AuthError",
            error_message="Auth failure after 3 consecutive 401s",
            created_at=datetime.now(UTC),
        )
        alerts.insert_alert(alert)
        all_alerts = alerts.get_all()
        assert len(all_alerts) == 1
        assert all_alerts[0].source == "otter_client"
        assert all_alerts[0].severity == "error"

    def test_multiple_alerts_maintain_order(self):
        alerts = InMemoryAlerts()
        a1 = EngineeringAlert(
            id=uuid4(),
            source="a",
            severity="info",
            error_class="E1",
            error_message="m1",
            created_at=datetime.now(UTC),
        )
        a2 = EngineeringAlert(
            id=uuid4(),
            source="b",
            severity="error",
            error_class="E2",
            error_message="m2",
            created_at=datetime.now(UTC),
        )
        alerts.insert_alert(a1)
        alerts.insert_alert(a2)
        all_alerts = alerts.get_all()
        assert len(all_alerts) == 2
        assert all_alerts[0].source == "a"
        assert all_alerts[1].source == "b"
