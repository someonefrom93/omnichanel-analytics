"""Tests for the Click CLI (run-bronze command) — task 4.2."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import patch

from omc_analytics.common.secrets import MerchantCredentials


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


# ---------------------------------------------------------------------------
# CLI smoke tests — Click IntRange validation
# ---------------------------------------------------------------------------


def test_cli_run_bronze_backfill_days_zero_rejected() -> None:
    """--backfill --backfill-days 0 is rejected by click.IntRange with non-zero exit."""
    from click.testing import CliRunner

    from omc_analytics.ingestion.run import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run-bronze",
            "--merchant-id",
            "M1",
            "--env",
            "dev",
            "--backfill",
            "--backfill-days",
            "0",
        ],
    )
    assert (
        result.exit_code != 0
    ), f"Expected non-zero exit for days=0, got {result.exit_code}"
    # IntRange should produce a clear error
    assert "backfill-days" in result.output or "Invalid value" in result.output


def test_cli_run_bronze_backfill_days_91_rejected() -> None:
    """--backfill --backfill-days 91 is rejected by click.IntRange with non-zero exit."""
    from click.testing import CliRunner

    from omc_analytics.ingestion.run import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run-bronze",
            "--merchant-id",
            "M1",
            "--env",
            "dev",
            "--backfill",
            "--backfill-days",
            "91",
        ],
    )
    assert (
        result.exit_code != 0
    ), f"Expected non-zero exit for days=91, got {result.exit_code}"
    assert "backfill-days" in result.output or "Invalid value" in result.output


# ---------------------------------------------------------------------------
# CLI integration tests — full run with moto + direct otter mocking
# ---------------------------------------------------------------------------


def test_cli_run_bronze_no_backfill_default() -> None:
    """Invoke run-bronze with no backfill flags. Assert exit0, 1 SUCCESS log row, 3 S3 objects.

    Regression test: T-1 path unchanged when backfill flags are absent.
    """
    import boto3
    import moto
    from click.testing import CliRunner

    from omc_analytics.common.logs import InMemoryLogs as RealInMemoryLogs
    from omc_analytics.common.secrets import InMemorySecrets as RealInMemorySecrets
    from omc_analytics.ingestion.run import cli

    logs = RealInMemoryLogs()
    secrets = RealInMemorySecrets()

    orders_payload = {"orders": [], "next_cursor": None}
    report_result_payload = {
        "status": "READY",
        "result": {
            "store_id": "merchant_001",
            "period_start": "2026-06-09T00:00:00Z",
            "period_end": "2026-06-09T23:59:59Z",
            "totals": {"gross_sales": {"amount": 0, "currency": "USD"}},
        },
    }

    with moto.mock_aws():
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="ofae-data-lakehouse-bronze-dev")

        secrets.save(_make_creds())

        with patch("omc_analytics.ingestion.run.logs_factory", return_value=logs):
            with patch(
                "omc_analytics.ingestion.run.secrets_factory", return_value=secrets
            ):
                with patch(
                    "omc_analytics.ingestion.run.OtterClient.fetch_orders",
                    return_value=orders_payload,
                ):
                    with patch(
                        "omc_analytics.ingestion.run.OtterClient.request_report",
                        return_value="job_abc123",
                    ):
                        with patch(
                            "omc_analytics.ingestion.run.OtterClient.poll_report",
                            return_value=report_result_payload,
                        ):
                            runner = CliRunner()
                            result = runner.invoke(
                                cli,
                                [
                                    "run-bronze",
                                    "--merchant-id",
                                    "merchant_001",
                                    "--env",
                                    "dev",
                                ],
                            )

        assert (
            result.exit_code == 0
        ), f"Expected exit 0, got {result.exit_code}: {result.output}"

        rows = logs.get_all()
        assert len(rows) == 1, f"Expected 1 log row, got {len(rows)}"
        assert rows[0].status == "SUCCESS"

        objects = s3_client.list_objects_v2(
            Bucket="ofae-data-lakehouse-bronze-dev"
        ).get("Contents", [])
        assert len(objects) == 3, f"Expected 3 S3 objects, got {len(objects)}"


def test_cli_run_bronze_with_backfill_flag() -> None:
    """Invoke run-bronze --backfill --backfill-days 3. Assert exit 0, 3 SUCCESS rows, 9 S3 objects."""
    import boto3
    import moto
    from click.testing import CliRunner

    from omc_analytics.common.logs import InMemoryLogs as RealInMemoryLogs
    from omc_analytics.common.secrets import InMemorySecrets as RealInMemorySecrets
    from omc_analytics.ingestion.run import cli

    logs = RealInMemoryLogs()
    secrets = RealInMemorySecrets()

    orders_payload = {"orders": [], "next_cursor": None}
    report_result_payload = {
        "status": "READY",
        "result": {
            "store_id": "merchant_001",
            "period_start": "2026-06-09T00:00:00Z",
            "period_end": "2026-06-09T23:59:59Z",
            "totals": {"gross_sales": {"amount": 0, "currency": "USD"}},
        },
    }

    with moto.mock_aws():
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="ofae-data-lakehouse-bronze-dev")

        secrets.save(_make_creds())

        with patch("omc_analytics.ingestion.run.logs_factory", return_value=logs):
            with patch(
                "omc_analytics.ingestion.run.secrets_factory", return_value=secrets
            ):
                with patch(
                    "omc_analytics.ingestion.run.compute_backfill_dates"
                ) as mock_dates:
                    mock_dates.return_value = [
                        date(2026, 6, 8),
                        date(2026, 6, 9),
                        date(2026, 6, 10),
                    ]
                    with patch(
                        "omc_analytics.ingestion.run.OtterClient.fetch_orders",
                        return_value=orders_payload,
                    ):
                        with patch(
                            "omc_analytics.ingestion.run.OtterClient.request_report",
                            return_value="job_abc123",
                        ):
                            with patch(
                                "omc_analytics.ingestion.run.OtterClient.poll_report",
                                return_value=report_result_payload,
                            ):
                                runner = CliRunner()
                                result = runner.invoke(
                                    cli,
                                    [
                                        "run-bronze",
                                        "--merchant-id",
                                        "merchant_001",
                                        "--env",
                                        "dev",
                                        "--backfill",
                                        "--backfill-days",
                                        "3",
                                    ],
                                )

        assert (
            result.exit_code == 0
        ), f"Expected exit 0, got {result.exit_code}: {result.output}"

        rows = logs.get_all()
        success_rows = [r for r in rows if r.status == "SUCCESS"]
        assert (
            len(success_rows) == 3
        ), f"Expected 3 SUCCESS rows, got {len(rows)} total: {rows}"

        objects = s3_client.list_objects_v2(
            Bucket="ofae-data-lakehouse-bronze-dev"
        ).get("Contents", [])
        assert len(objects) == 9, f"Expected 9 S3 objects, got {len(objects)}"


def test_cli_run_bronze_no_backfill_flag() -> None:
    """Invoke run-bronze --no-backfill (explicit). Same as default: 1 SUCCESS row, 3 S3 objects."""
    import boto3
    import moto
    from click.testing import CliRunner

    from omc_analytics.common.logs import InMemoryLogs as RealInMemoryLogs
    from omc_analytics.common.secrets import InMemorySecrets as RealInMemorySecrets
    from omc_analytics.ingestion.run import cli

    logs = RealInMemoryLogs()
    secrets = RealInMemorySecrets()

    orders_payload = {"orders": [], "next_cursor": None}
    report_result_payload = {
        "status": "READY",
        "result": {
            "store_id": "merchant_001",
            "period_start": "2026-06-09T00:00:00Z",
            "period_end": "2026-06-09T23:59:59Z",
            "totals": {"gross_sales": {"amount": 0, "currency": "USD"}},
        },
    }

    with moto.mock_aws():
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="ofae-data-lakehouse-bronze-dev")

        secrets.save(_make_creds())

        with patch("omc_analytics.ingestion.run.logs_factory", return_value=logs):
            with patch(
                "omc_analytics.ingestion.run.secrets_factory", return_value=secrets
            ):
                with patch(
                    "omc_analytics.ingestion.run.OtterClient.fetch_orders",
                    return_value=orders_payload,
                ):
                    with patch(
                        "omc_analytics.ingestion.run.OtterClient.request_report",
                        return_value="job_abc123",
                    ):
                        with patch(
                            "omc_analytics.ingestion.run.OtterClient.poll_report",
                            return_value=report_result_payload,
                        ):
                            runner = CliRunner()
                            result = runner.invoke(
                                cli,
                                [
                                    "run-bronze",
                                    "--merchant-id",
                                    "merchant_001",
                                    "--env",
                                    "dev",
                                    "--no-backfill",
                                ],
                            )

        assert (
            result.exit_code == 0
        ), f"Expected exit 0, got {result.exit_code}: {result.output}"

        rows = logs.get_all()
        assert len(rows) == 1, f"Expected 1 log row, got {len(rows)}"
        assert rows[0].status == "SUCCESS"

        objects = s3_client.list_objects_v2(
            Bucket="ofae-data-lakehouse-bronze-dev"
        ).get("Contents", [])
        assert len(objects) == 3, f"Expected 3 S3 objects, got {len(objects)}"


def test_cli_run_bronze_backfill_failure_exits_1() -> None:
    """--backfill --backfill-days 2 with otter failure on day 2: exit code 1, day 1 SUCCESS, day 2 FAILED."""
    import boto3
    import moto
    import responses
    from click.testing import CliRunner

    from omc_analytics.common.logs import InMemoryLogs as RealInMemoryLogs
    from omc_analytics.common.secrets import InMemorySecrets as RealInMemorySecrets
    from omc_analytics.ingestion.run import cli

    logs = RealInMemoryLogs()
    secrets = RealInMemorySecrets()

    orders_payload = {"orders": [], "next_cursor": None}
    report_result_payload = {
        "status": "READY",
        "result": {
            "store_id": "merchant_001",
            "period_start": "2026-06-09T00:00:00Z",
            "period_end": "2026-06-09T23:59:59Z",
            "totals": {"gross_sales": {"amount": 0, "currency": "USD"}},
        },
    }

    call_count = 0

    def otter_orders_side_effect(store_id: str, start_utc: Any, end_utc: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise Exception("OtterAPIError: simulated network failure on day 2")
        return orders_payload

    with moto.mock_aws():
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="ofae-data-lakehouse-bronze-dev")

        secrets.save(_make_creds())

        with responses.RequestsMock(assert_all_requests_are_fired=False) as rs:
            for _ in range(10):
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
                    json=report_result_payload,
                    status=200,
                )

            with patch("omc_analytics.ingestion.run.logs_factory", return_value=logs):
                with patch(
                    "omc_analytics.ingestion.run.secrets_factory",
                    return_value=secrets,
                ):
                    with patch(
                        "omc_analytics.ingestion.run.compute_backfill_dates"
                    ) as mock_dates:
                        mock_dates.return_value = [
                            date(2026, 6, 9),
                            date(2026, 6, 10),
                        ]
                        with patch(
                            "omc_analytics.ingestion.run.OtterClient.fetch_orders",
                            side_effect=otter_orders_side_effect,
                        ):
                            with patch(
                                "omc_analytics.ingestion.run.OtterClient.request_report",
                                return_value="job_abc123",
                            ):
                                with patch(
                                    "omc_analytics.ingestion.run.OtterClient.poll_report",
                                    return_value=report_result_payload,
                                ):
                                    runner = CliRunner()
                                    result = runner.invoke(
                                        cli,
                                        [
                                            "run-bronze",
                                            "--merchant-id",
                                            "merchant_001",
                                            "--env",
                                            "dev",
                                            "--backfill",
                                            "--backfill-days",
                                            "2",
                                        ],
                                    )

        assert (
            result.exit_code == 1
        ), f"Expected exit1 on partial failure, got {result.exit_code}: {result.output}"

        rows = logs.get_all()
        success_rows = [r for r in rows if r.status == "SUCCESS"]
        failed_rows = [r for r in rows if r.status == "FAILED"]

        assert (
            len(success_rows) == 1
        ), f"Expected 1 SUCCESS row, got {len(success_rows)}"
        assert len(failed_rows) == 1, f"Expected 1 FAILED row, got {len(failed_rows)}"
        assert failed_rows[0].error_class is not None
