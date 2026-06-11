"""End-to-end Bronze ingestion pipeline integration tests.

These tests exercise the full stack with moto[s3] + responses.
They are opt-in via `pytest -m integration` — skipped by default.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import boto3
import moto
import pytest
import responses

from omc_analytics.common.logs import InMemoryLogs
from omc_analytics.common.secrets import InMemorySecrets
from omc_analytics.ingestion.run import _build_deps, run_bronze_impl

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_fixture(name: str) -> dict:
    """Load a JSON fixture by name, stripping our provenance metadata."""
    path = Path(__file__).parent.parent / "fixtures" / "otter" / f"{name}.json"
    raw = json.loads(path.read_text())
    return {
        k: v
        for k, v in raw.items()
        if k not in ("provenance", "fixture_version", "endpoint")
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def logs() -> InMemoryLogs:
    return InMemoryLogs()


@pytest.fixture
def secrets() -> InMemorySecrets:
    return InMemorySecrets()


# ---------------------------------------------------------------------------
# Integration tests — slow, opt-in
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_full_pipeline_creates_hive_partitioned_objects(
    logs: InMemoryLogs,
    secrets: InMemorySecrets,
) -> None:
    """Happy-path: S3 contains 4 objects at expected Hive-partitioned keys.

    Objects: 1 orders, 1 reports_enqueue, 1 reports_result.
    Each key follows: otter/merchant_id={id}/year=YYYY/month=MM/day=DD/{endpoint}.json
    """
    orders_payload = load_fixture("orders_response")
    report_enqueue_payload = load_fixture("reports_enqueue_response")
    report_result_payload = load_fixture("reports_result_ready")

    with moto.mock_aws():
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="ofae-data-lakehouse-bronze-dev")

        # Pre-seed credentials (merchant_001 has access_token)
        from datetime import UTC

        from omc_analytics.common.secrets import MerchantCredentials

        secrets.save(
            MerchantCredentials(
                merchant_id="merchant_001",
                public_api_url="https://api.otter.dev",
                client_id="dev-client-id",
                client_secret_encrypted="dev-client-secret",
                access_token="dev-token-abc123",
                refresh_token="dev-refresh-xyz",
                expires_at=__import__("datetime").datetime(
                    2099, 12, 31, 23, 59, 59, tzinfo=UTC
                ),
            )
        )

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

            run_ctx = _build_deps(
                merchant_id="merchant_001",
                env="dev",
                secrets=secrets,
                logs=logs,
                s3_client=s3_client,
            )[
                -1
            ]  # _build_deps returns tuple; last element is RunContext

            run_bronze_impl(run_ctx)

        # Verify logs
        rows = logs.get_all()
        assert len(rows) == 1, f"Expected 1 log row, got {len(rows)}: {rows}"
        assert rows[0].status == "SUCCESS", f"Expected SUCCESS, got {rows[0].status}"

        # Verify S3 objects
        objects = s3_client.list_objects_v2(
            Bucket="ofae-data-lakehouse-bronze-dev"
        ).get("Contents", [])
        assert (
            len(objects) == 3
        ), f"Expected 3 S3 objects, got {len(objects)}: {[o['Key'] for o in objects]}"

        # Verify each key follows Hive partitioning
        for obj in objects:
            key = obj["Key"]
            assert key.startswith(
                "otter/merchant_id=merchant_001/"
            ), f"Key does not match partition scheme: {key}"
            # Check it looks like a date partition: year=YYYY/month=MM/day=DD/
            assert (
                "/year=" in key and "/month=" in key and "/day=" in key
            ), f"Key missing Hive partition: {key}"
            # Check endpoint and timestamp suffix
            assert any(
                ep in key for ep in ("orders-", "reports_enqueue-", "reports_result-")
            ), f"Key missing endpoint: {key}"


@pytest.mark.integration
def test_full_pipeline_recovers_from_401_using_refresh(
    logs: InMemoryLogs,
    secrets: InMemorySecrets,
) -> None:
    """Otter returns 401 twice, then 200. The run should still succeed."""
    orders_payload = load_fixture("orders_response")
    report_enqueue_payload = load_fixture("reports_enqueue_response")
    report_result_payload = load_fixture("reports_result_ready")

    with moto.mock_aws():
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="ofae-data-lakehouse-bronze-dev")

        from datetime import UTC

        from omc_analytics.common.secrets import MerchantCredentials

        secrets.save(
            MerchantCredentials(
                merchant_id="merchant_001",
                public_api_url="https://api.otter.dev",
                client_id="dev-client-id",
                client_secret_encrypted="dev-client-secret",
                access_token="expired-token",
                refresh_token="refreshed-token-xyz",
                expires_at=__import__("datetime").datetime(
                    2099, 12, 31, 23, 59, 59, tzinfo=UTC
                ),
            )
        )

        # Simulate: 401 on orders, then 401 again, then 200
        with responses.RequestsMock() as rs:
            rs.add(
                responses.GET,
                "https://api.otter.dev/v1/orders",
                json={"error": "Unauthorized"},
                status=401,
            )
            rs.add(
                responses.GET,
                "https://api.otter.dev/v1/orders",
                json={"error": "Unauthorized"},
                status=401,
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
                json=report_enqueue_payload,
                status=200,
            )
            rs.add(
                responses.GET,
                "https://api.otter.dev/v1/reports/job_abc123",
                json=report_result_payload,
                status=200,
            )

            run_ctx = _build_deps(
                merchant_id="merchant_001",
                env="dev",
                secrets=secrets,
                logs=logs,
                s3_client=s3_client,
            )[-1]

            run_bronze_impl(run_ctx)

        rows = logs.get_all()
        assert len(rows) == 1
        assert rows[0].status == "SUCCESS"


@pytest.mark.integration
def test_full_pipeline_retries_429_with_backoff(
    logs: InMemoryLogs,
    secrets: InMemorySecrets,
) -> None:
    """Otter returns 429 twice, then 200. Run succeeds and time.sleep was called."""
    orders_payload = load_fixture("orders_response")
    report_enqueue_payload = load_fixture("reports_enqueue_response")
    report_result_payload = load_fixture("reports_result_ready")

    with moto.mock_aws():
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="ofae-data-lakehouse-bronze-dev")

        from datetime import UTC

        from omc_analytics.common.secrets import MerchantCredentials

        secrets.save(
            MerchantCredentials(
                merchant_id="merchant_001",
                public_api_url="https://api.otter.dev",
                client_id="dev-client-id",
                client_secret_encrypted="dev-client-secret",
                access_token="dev-token-abc123",
                refresh_token="dev-refresh-xyz",
                expires_at=__import__("datetime").datetime(
                    2099, 12, 31, 23, 59, 59, tzinfo=UTC
                ),
            )
        )

        sleep_calls: list = []

        def track_sleep(duration: float) -> None:
            sleep_calls.append(duration)

        with responses.RequestsMock() as rs:
            rs.add(
                responses.GET,
                "https://api.otter.dev/v1/orders",
                json={"error": "rate limited"},
                status=429,
            )
            rs.add(
                responses.GET,
                "https://api.otter.dev/v1/orders",
                json={"error": "rate limited"},
                status=429,
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
                json=report_enqueue_payload,
                status=200,
            )
            rs.add(
                responses.GET,
                "https://api.otter.dev/v1/reports/job_abc123",
                json=report_result_payload,
                status=200,
            )

            run_ctx = _build_deps(
                merchant_id="merchant_001",
                env="dev",
                secrets=secrets,
                logs=logs,
                s3_client=s3_client,
            )[-1]

            with patch(
                "omc_analytics.ingestion.otter_client.time.sleep",
                side_effect=track_sleep,
            ):
                run_bronze_impl(run_ctx)

        rows = logs.get_all()
        assert len(rows) == 1
        assert rows[0].status == "SUCCESS"

        # With RetryPolicy(max_retries=3, base=1.0, cap=8.0), first 429 should sleep ~1s
        assert (
            len(sleep_calls) == 2
        ), f"Expected 2 sleep calls for 2x 429, got {len(sleep_calls)}: {sleep_calls}"
        # Both sleeps should be non-zero (backoff applied)
        assert all(
            s > 0 for s in sleep_calls
        ), f"Expected positive sleep durations, got {sleep_calls}"
