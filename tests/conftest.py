"""Shared pytest fixtures for omc-analytics tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import freezegun
import pytest

# ---------------------------------------------------------------------------
# In-memory secrets stub
# ---------------------------------------------------------------------------


class InMemorySecrets:
    """PR1 stub for SecretsPort — holds credentials in a dict, no KMS."""

    def __init__(self, initial: dict[str, dict[str, Any]] | None = None) -> None:
        self._store: dict[str, dict[str, Any]] = initial or {}

    def load_credentials(self, merchant_id: str) -> dict[str, Any]:
        if merchant_id not in self._store:
            raise KeyError(f"No credentials found for merchant_id={merchant_id}")
        return self._store[merchant_id].copy()

    def save_credentials(self, merchant_id: str, payload: dict[str, Any]) -> None:
        self._store[merchant_id] = payload.copy()


@pytest.fixture
def in_memory_secrets() -> InMemorySecrets:
    """Provides an empty InMemorySecrets stub."""
    return InMemorySecrets()


@pytest.fixture
def in_memory_secrets_with_creds(
    in_memory_secrets: InMemorySecrets,
) -> InMemorySecrets:
    """Provides an InMemorySecrets pre-loaded with typical dev credentials."""
    in_memory_secrets.save_credentials(
        "merchant_001",
        {
            "access_token": "dev-token-abc123",
            "expires_at": int(
                datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC).timestamp()
            ),
            "public_api_url": "https://api.otter.dev",
            "store_id": "store_001",
            "store_tz": "America/New_York",
            "client_id": "dev-client-id",
            "client_secret": "dev-client-secret",
        },
    )
    return in_memory_secrets


# ---------------------------------------------------------------------------
# In-memory logs stub
# ---------------------------------------------------------------------------


class InMemoryLogs:
    """PR1 stub for LogsPort — append-only list, no Postgres."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []

    def insert_started(self, row: dict[str, Any]) -> str:
        run_id = row.get("run_id", "unknown")
        self._rows.append(
            {
                **row,
                "status": "STARTED",
            }
        )
        return run_id

    def update_finished(
        self,
        run_id: str,
        status: str,
        error_class: str | None,
        error_message: str | None,
    ) -> None:
        for row in self._rows:
            if row.get("run_id") == run_id and row.get("status") == "STARTED":
                row["status"] = status
                row["error_class"] = error_class
                row["error_message"] = error_message
                break

    def get_rows(self) -> list[dict[str, Any]]:
        return self._rows.copy()


@pytest.fixture
def in_memory_logs() -> InMemoryLogs:
    """Provides an empty InMemoryLogs stub."""
    return InMemoryLogs()


# ---------------------------------------------------------------------------
# Frozen clock
# ---------------------------------------------------------------------------


@pytest.fixture
def frozen_clock() -> freezegun.api.FrozenTime:
    """Provides a freezegun.frozen_time context manager for time-dependent tests."""
    return freezegun.freeze_time("2025-01-15 12:00:00", tz_offset=0)


# ---------------------------------------------------------------------------
# Settings dict (fakeredis-free)
# ---------------------------------------------------------------------------


@pytest.fixture
def settings_dict() -> dict[str, Any]:
    """Provides a plain dict of app settings — no redis, no external deps."""
    return {
        "env": "dev",
        "s3_bucket": "ofae-data-lakehouse-bronze-dev",
        "public_api_url": "https://api.otter.dev",
        "log_level": "INFO",
        "retry_max_attempts": 3,
        "retry_base_seconds": 1.0,
        "retry_cap_seconds": 60.0,
        "oauth_pre_expiry_seconds": 600,
    }


@pytest.fixture
def responses_mock():
    """Provides a pre-configured responses mock for HTTP mocking."""
    import responses

    with responses.RequestsMock() as rs:
        yield rs


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def load_fixture():
    """Return a helper that strips provenance metadata from a fixture dict."""
    from pathlib import Path

    def _load(name: str) -> dict:
        """Load a JSON fixture by name, stripping our provenance metadata.

        The raw fixture has three extra keys: provenance, fixture_version, endpoint.
        These are stripped so the returned dict matches the raw Otter API response.
        """
        path = Path(__file__).parent / "fixtures" / "otter" / f"{name}.json"
        raw = __import__("json").loads(path.read_text())
        return {
            k: v
            for k, v in raw.items()
            if k not in ("provenance", "fixture_version", "endpoint")
        }

    return _load


# ---------------------------------------------------------------------------
# moto S3 fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def moto_s3():
    """Provides a moto-mocked boto3 S3 client and ensures the dev bucket exists."""
    import boto3
    import moto

    with moto.mock_aws():
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="ofae-data-lakehouse-bronze-dev")
        yield s3_client


# ---------------------------------------------------------------------------
# mock dbt runner fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_dbt_runner():
    """Provides a mock dbtRunner that returns success=True by default."""
    from unittest.mock import MagicMock, patch

    mock_result = MagicMock()
    mock_result.success = True

    with patch("omc_analytics.transformation.dbt_runner.dbtRunner") as mock_cls:
        mock_runner = MagicMock()
        mock_runner.invoke.return_value = mock_result
        mock_cls.return_value = mock_runner
        yield mock_runner


# ---------------------------------------------------------------------------
# otter_responses fixture — pre-registers common Otter endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def otter_responses():
    """Pre-registers responses for the three Otter endpoints used in Bronze ingestion.

    Returns a configured responses.RequestsMock context manager.
    Tests should wrap HTTP calls with this fixture.
    """
    import responses

    orders_payload = {"orders": [], "next_cursor": None}
    report_enqueue_payload = {"jobId": "job_abc123", "status": "QUEUED"}
    report_result_payload = {
        "status": "READY",
        "result": {
            "store_id": "merchant_001",
            "period_start": "2026-06-09T00:00:00Z",
            "period_end": "2026-06-09T23:59:59Z",
            "totals": {"gross_sales": {"amount": 0, "currency": "USD"}},
        },
    }

    with responses.RequestsMock() as rs:
        rs.add(
            responses.GET,
            "https://api.otter.dev/v1/orders",
            json=orders_payload,
            status=200,
        )
        rs.add(
            responses.POST,
            "https://api.otter.dev/v1/reports",
            json=report_enqueue_payload,
            status=200,
        )
        rs.add(
            responses.GET,
            "https://api.otter.dev/v1/reports/job_abc123",
            json=report_result_payload,
            status=200,
        )
        yield rs
