"""Tests for ingestion/run.py — CLI orchestration and pure helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from omc_analytics.common.logs import InMemoryLogs
from omc_analytics.common.secrets import (
    InMemorySecrets,
    MerchantCredentials,
)
from omc_analytics.ingestion.backoff import RetryPolicy
from omc_analytics.ingestion.errors import (
    ReportJobCancelledError,
    ReportJobFailedError,
    ReportPollingExhaustedError,
)

# ---------------------------------------------------------------------------
# compute_t1_window tests
# ---------------------------------------------------------------------------


def test_compute_t1_window_handles_dst_transition() -> None:
    """At DST spring-forward boundary in Buenos Aires (UTC-3→UTC-2), T-1 window crosses the shift.

    On 2026-10-03 02:00 local (Buenos Aires) clocks spring forward to 03:00.
    Run at 01:00 Buenos Aires (04:00 UTC) — before the DST transition.
    T-1 in Buenos Aires is 2026-10-02. The day has only 23 hours due to DST.
    The window should be [2026-10-02 00:00 local, 2026-10-02 23:59:59.999999 local].
    In UTC that is [2026-10-02 03:00Z, 2026-10-03 02:59:59.999999Z].
    """
    from omc_analytics.ingestion.run import compute_t1_window

    store_tz = ZoneInfo("America/Argentina/Buenos_Aires")
    # 2026-10-03 04:00 UTC = 2026-10-03 01:00 Buenos Aires (before DST shift at 02:00)
    now_utc = datetime(2026, 10, 3, 4, 0, 0, tzinfo=UTC)

    start, end = compute_t1_window(store_tz, now_utc)

    expected_start = datetime(2026, 10, 2, 3, 0, 0, tzinfo=UTC)
    expected_end = datetime(2026, 10, 3, 2, 59, 59, 999999, tzinfo=UTC)

    assert start == expected_start, f"Expected start {expected_start}, got {start}"
    assert end == expected_end, f"Expected end {expected_end}, got {end}"


def test_compute_t1_window_uses_store_tz_not_utc() -> None:
    """Store in UTC-5 (Bogota). Run at 01:00 UTC. T-1 should be 2 days back in local.

    Bogota is UTC-5, no DST.
    At 01:00 UTC on 2026-06-11, local time in Bogota is 2026-06-10 20:00.
    T-1 in Bogota is 2026-06-09 (yesterday local is 2026-06-10, so T-1 is 2026-06-09).
    """
    from omc_analytics.ingestion.run import compute_t1_window

    store_tz = ZoneInfo("America/Bogota")
    # 2026-06-11 01:00 UTC = 2026-06-10 20:00 Bogota
    now_utc = datetime(2026, 6, 11, 1, 0, 0, tzinfo=UTC)

    start, end = compute_t1_window(store_tz, now_utc)

    # T-1 in Bogota is 2026-06-09 00:00 local = 2026-06-09 05:00Z
    expected_start = datetime(2026, 6, 9, 5, 0, 0, tzinfo=UTC)
    # T-1 end: 2026-06-09 23:59:59.999999 local = 2026-06-10 04:59:59.999999Z
    expected_end = datetime(2026, 6, 10, 4, 59, 59, 999999, tzinfo=UTC)

    assert start == expected_start, f"Expected start {expected_start}, got {start}"
    assert end == expected_end, f"Expected end {expected_end}, got {end}"


# ---------------------------------------------------------------------------
# poll_report_until_ready tests
# ---------------------------------------------------------------------------


def test_poll_report_until_ready_returns_on_status_ready() -> None:
    """Three calls: PENDING, PENDING, READY → returns the READY payload."""
    from omc_analytics.ingestion.run import poll_report_until_ready

    mock_otter = MagicMock()
    # Simulate: PENDING, PENDING, READY
    mock_otter.poll_report.side_effect = [
        {"status": "PENDING"},
        {"status": "PENDING"},
        {
            "status": "READY",
            "result": {
                "store_id": "merchant_001",
                "period_start": "2026-06-09T00:00:00Z",
            },
        },
    ]

    policy = RetryPolicy(max_retries=5, base_seconds=0.1, cap_seconds=1.0, jitter=False)
    clock = MagicMock(return_value=datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC))

    with patch("omc_analytics.ingestion.run.time.sleep") as mock_sleep:
        result = poll_report_until_ready(
            mock_otter, "store_001", "job_abc", policy, clock
        )

    assert result["status"] == "READY"
    assert mock_otter.poll_report.call_count == 3
    # Should have slept twice (once per PENDING before READY)
    assert mock_sleep.call_count == 2


def test_poll_report_until_ready_raises_on_failed() -> None:
    """Two calls: PENDING, FAILED → ReportJobFailedError propagates."""
    from omc_analytics.ingestion.run import poll_report_until_ready

    mock_otter = MagicMock()
    mock_otter.poll_report.side_effect = [
        {"status": "PENDING"},
        ReportJobFailedError("job_abc"),
    ]

    policy = RetryPolicy(max_retries=5, base_seconds=0.1, cap_seconds=1.0, jitter=False)
    clock = MagicMock(return_value=datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC))

    with patch("omc_analytics.ingestion.run.time.sleep") as mock_sleep:
        with pytest.raises(ReportJobFailedError):
            poll_report_until_ready(mock_otter, "store_001", "job_abc", policy, clock)

    assert mock_sleep.call_count == 1  # Slept once before FAILED


def test_poll_report_until_ready_raises_on_cancelled() -> None:
    """Two calls: PENDING, CANCELLED → ReportJobCancelledError propagates."""
    from omc_analytics.ingestion.run import poll_report_until_ready

    mock_otter = MagicMock()
    mock_otter.poll_report.side_effect = [
        {"status": "PENDING"},
        ReportJobCancelledError("job_abc"),
    ]

    policy = RetryPolicy(max_retries=5, base_seconds=0.1, cap_seconds=1.0, jitter=False)
    clock = MagicMock(return_value=datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC))

    with patch("omc_analytics.ingestion.run.time.sleep") as mock_sleep:
        with pytest.raises(ReportJobCancelledError):
            poll_report_until_ready(mock_otter, "store_001", "job_abc", policy, clock)

    assert mock_sleep.call_count == 1


def test_poll_report_until_ready_exhausts_after_max_attempts() -> None:
    """Always returns PENDING, policy max_retries=3 → ReportPollingExhaustedError."""
    from omc_analytics.ingestion.run import poll_report_until_ready

    mock_otter = MagicMock()
    # Return transient status every time
    mock_otter.poll_report.return_value = {"status": "PENDING"}

    policy = RetryPolicy(
        max_retries=3, base_seconds=0.05, cap_seconds=1.0, jitter=False
    )
    clock = MagicMock(return_value=datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC))

    with patch("omc_analytics.ingestion.run.time.sleep") as mock_sleep:
        with pytest.raises(ReportPollingExhaustedError) as exc_info:
            poll_report_until_ready(mock_otter, "store_001", "job_abc", policy, clock)

    assert exc_info.value.job_id == "job_abc"
    assert exc_info.value.max_retries == 3
    # 3 poll attempts (initial + 2 retries) + 2 sleeps between them
    assert mock_otter.poll_report.call_count == 3
    assert mock_sleep.call_count == 2  # Sleep between attempt 1→2 and 2→3


# ---------------------------------------------------------------------------
# Helpers to build a minimal RunContext for testing
# ---------------------------------------------------------------------------


def _make_creds(merchant_id: str = "merchant_001") -> MerchantCredentials:
    return MerchantCredentials(
        merchant_id=merchant_id,
        public_api_url="https://api.otter.dev",
        client_id="dev-client-id",
        client_secret_encrypted="dev-client-secret",
        access_token="dev-token-abc123",
        refresh_token="dev-refresh-xyz",
        expires_at=datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC),
    )


def _build_run_context(
    secrets: InMemorySecrets,
    logs: InMemoryLogs,
    s3_client: MagicMock,
):
    """Build a minimal RunContext for testing run_bronze_impl."""
    from omc_analytics.ingestion.run import _build_deps

    _secrets, _logs, _oauth, _otter, _bronze, run_ctx = _build_deps(
        merchant_id="merchant_001",
        env="dev",
        secrets=secrets,
        logs=logs,
        s3_client=s3_client,
    )
    return run_ctx


# ---------------------------------------------------------------------------
# run_bronze_impl tests
# ---------------------------------------------------------------------------


def test_run_bronze_impl_happy_path() -> None:
    """Full end-to-end with responses for Otter endpoints, moto for S3.

    Asserts: 2 orders written, 1 reports_enqueue, 1 reports_result.
    Asserts: 1 log row with status=SUCCESS.
    """
    import boto3
    import moto
    import responses

    from omc_analytics.common.logs import InMemoryLogs as RealInMemoryLogs
    from omc_analytics.common.secrets import InMemorySecrets as RealInMemorySecrets
    from omc_analytics.ingestion.run import run_bronze_impl

    logs = RealInMemoryLogs()
    secrets = RealInMemorySecrets()

    orders_payload = {
        "orders": [
            {
                "id": "ord_001",
                "store_id": "merchant_001",
                "channel": "ubereats",
                "created_at": "2026-06-10T12:00:00Z",
                "total": {"amount": 2500, "currency": "USD"},
                "items": [
                    {
                        "sku": "BURGER_CLASSIC",
                        "name": "Classic Burger",
                        "qty": 1,
                        "unit_price": {"amount": 1200, "currency": "USD"},
                    }
                ],
                "customer": {
                    "name_hash": "<sha256-of-john-doe>",
                    "phone_hash": "<sha256-of-555-5555>",
                },
            },
            {
                "id": "ord_002",
                "store_id": "merchant_001",
                "channel": "doordash",
                "created_at": "2026-06-10T13:00:00Z",
                "total": {"amount": 1800, "currency": "USD"},
                "items": [
                    {
                        "sku": "FRIES_MEDIUM",
                        "name": "Medium Fries",
                        "qty": 2,
                        "unit_price": {"amount": 400, "currency": "USD"},
                    }
                ],
                "customer": {
                    "name_hash": "<sha256-of-jane-doe>",
                    "phone_hash": "<sha256-of-555-5556>",
                },
            },
        ],
        "next_cursor": None,
    }

    report_enqueue_payload = {"jobId": "job_abc123", "status": "QUEUED"}

    report_result_payload = {
        "status": "READY",
        "result": {
            "store_id": "merchant_001",
            "period_start": "2026-06-09T00:00:00Z",
            "period_end": "2026-06-09T23:59:59Z",
            "totals": {
                "gross_sales": {"amount": 12500, "currency": "USD"},
                "net_payout": {"amount": 8750, "currency": "USD"},
            },
        },
    }

    with moto.mock_aws():
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="ofae-data-lakehouse-bronze-dev")

        secrets.save(_make_creds())

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

            run_ctx = _build_run_context(secrets, logs, s3_client)
            run_bronze_impl(run_ctx)

        rows = logs.get_all()
        assert len(rows) == 1
        assert rows[0].status == "SUCCESS"
        assert rows[0].error_class is None

        objects = s3_client.list_objects_v2(
            Bucket="ofae-data-lakehouse-bronze-dev"
        ).get("Contents", [])
        assert (
            len(objects) == 3
        ), f"Expected 3 S3 objects, got {len(objects)}: {objects}"


def test_run_bronze_impl_writes_failed_log_on_error() -> None:
    """Inject a 500 from Otter on orders call. Assert FAILED log with error_class set."""
    import boto3
    import moto
    import responses

    from omc_analytics.common.logs import InMemoryLogs as RealInMemoryLogs
    from omc_analytics.common.secrets import InMemorySecrets as RealInMemorySecrets
    from omc_analytics.ingestion.run import run_bronze_impl

    logs = RealInMemoryLogs()
    secrets = RealInMemorySecrets()

    with moto.mock_aws():
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="ofae-data-lakehouse-bronze-dev")

        secrets.save(_make_creds())

        with responses.RequestsMock() as rs:
            rs.add(
                responses.GET,
                "https://api.otter.dev/v1/orders",
                json={"error": "internal server error"},
                status=500,
            )

            run_ctx = _build_run_context(secrets, logs, s3_client)

            from omc_analytics.ingestion.errors import OtterAPIError

            with pytest.raises(OtterAPIError):
                run_bronze_impl(run_ctx)

        rows = logs.get_all()
        assert len(rows) == 1
        assert rows[0].status == "FAILED"
        assert rows[0].error_class == "OtterAPIError"
        assert rows[0].error_message is not None


def test_run_bronze_impl_bootstraps_credentials_on_first_run() -> None:
    """InMemorySecrets empty initially; assert after run, secrets has the merchant."""
    import boto3
    import moto
    import responses

    from omc_analytics.common.logs import InMemoryLogs as RealInMemoryLogs
    from omc_analytics.common.secrets import InMemorySecrets as RealInMemorySecrets
    from omc_analytics.ingestion.run import run_bronze_impl

    logs = RealInMemoryLogs()
    secrets = RealInMemorySecrets()

    oauth_token_payload = {
        "access_token": "bootstrapped-token-xyz",
        "expires_in": 2627999,
        "refresh_token": "rt_xyz789",
        "token_type": "bearer",
        "scope": "orders.read reports.generate_report",
    }

    orders_payload = {
        "orders": [],
        "next_cursor": None,
    }

    with moto.mock_aws():
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="ofae-data-lakehouse-bronze-dev")

        assert len(secrets._store) == 0

        with responses.RequestsMock() as rs:
            rs.add(
                responses.POST,
                "https://api.otter.dev/v1/auth/token",
                json=oauth_token_payload,
                status=200,
            )
            rs.add(
                responses.GET,
                "https://api.otter.dev/v1/orders",
                json=orders_payload,
                status=200,
            )
            rs.add(
                responses.POST,
                "https://api.otter.dev/v1/reports",
                json={"jobId": "job_abc123", "status": "QUEUED"},
                status=200,
            )
            rs.add(
                responses.GET,
                "https://api.otter.dev/v1/reports/job_abc123",
                json={
                    "status": "READY",
                    "result": {
                        "store_id": "merchant_001",
                        "period_start": "2026-06-09T00:00:00Z",
                        "period_end": "2026-06-09T23:59:59Z",
                        "totals": {"gross_sales": {"amount": 0, "currency": "USD"}},
                    },
                },
                status=200,
            )

            with patch.dict(
                "os.environ",
                {
                    "OTTER_CLIENT_ID": "dev-client-id",
                    "OTTER_CLIENT_SECRET": "dev-client-secret",
                },
            ):
                run_ctx = _build_run_context(secrets, logs, s3_client)
                run_bronze_impl(run_ctx)

        assert "merchant_001" in secrets._store
        creds = secrets.load("merchant_001")
        assert creds.access_token == "bootstrapped-token-xyz"
