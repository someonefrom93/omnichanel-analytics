"""ingestion/run.py — CLI orchestration for the Bronze ingestion pipeline.

PR1 uses InMemorySecrets and InMemoryLogs stubs.
PR2 swaps these for KMS-backed secrets and Postgres-backed logs.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

import boto3
import click
import requests

from omc_analytics.common.config import RunContext
from omc_analytics.common.logs import InMemoryLogs, RunLog
from omc_analytics.common.secrets import (
    InMemorySecrets,
    MerchantNotFoundError,
)
from omc_analytics.ingestion.backoff import RetryPolicy
from omc_analytics.ingestion.bronze_writer import BronzeWriter
from omc_analytics.ingestion.errors import (
    ReportJobCancelledError,
    ReportJobFailedError,
    ReportPollingExhaustedError,
)
from omc_analytics.ingestion.oauth import OAuthRefresher
from omc_analytics.ingestion.otter_client import OtterClient

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def compute_t1_window(store_tz: Any, now_utc: datetime) -> tuple[datetime, datetime]:
    """Compute the T-1 (yesterday) window in UTC for a store's local timezone.

    Args:
        store_tz: A ZoneInfo for the store's local timezone.
        now_utc: The current time in UTC.

    Returns:
        A tuple (window_start_utc, window_end_utc) representing the
        T-1 day in the store's local timezone, expressed as UTC datetimes.
        window_start_utc is the local midnight of yesterday.
        window_end_utc is 23:59:59.999999 of yesterday in local time, as UTC.
    """
    now_local = now_utc.astimezone(store_tz)
    yesterday_local = now_local - timedelta(days=1)
    t1_start_local = yesterday_local.replace(hour=0, minute=0, second=0, microsecond=0)
    t1_end_local = yesterday_local.replace(
        hour=23, minute=59, second=59, microsecond=999999
    )
    return (
        t1_start_local.astimezone(UTC),
        t1_end_local.astimezone(UTC),
    )


def poll_report_until_ready(
    otter: OtterClient,
    store_id: str,
    job_id: str,
    policy: RetryPolicy,
    clock: Callable[[], datetime],
) -> dict:
    """Poll a report job until READY, or raise on FAILED/CANCELLED/exhaustion.

    Args:
        otter: An OtterClient instance.
        store_id: The store identifier.
        job_id: The job identifier to poll.
        policy: RetryPolicy controlling the polling loop (max_retries, base, cap).
        clock: A callable returning the current datetime.

    Returns:
        The full response dict when status==READY.

    Raises:
        ReportJobFailedError: If the job status is FAILED.
        ReportJobCancelledError: If the job status is CANCELLED.
        ReportPollingExhaustedError: If polling exhausts max_retries without READY.
    """
    attempt = 0
    while True:
        attempt += 1
        result = otter.poll_report(store_id, job_id)
        status = result.get("status")

        if status == "READY":
            return result
        if status == "FAILED":
            raise ReportJobFailedError(job_id)
        if status == "CANCELLED":
            raise ReportJobCancelledError(job_id)

        if attempt >= policy.max_retries:
            raise ReportPollingExhaustedError(job_id, policy.max_retries)

        wait_time = policy.wait_for(attempt)
        time.sleep(wait_time)


# ---------------------------------------------------------------------------
# Pure orchestration logic (testable without Click)
# ---------------------------------------------------------------------------


def run_bronze_impl(run_ctx: RunContext) -> None:
    """Pure orchestration logic for one Bronze ingestion run.

    Args:
        run_ctx: A fully-populated RunContext with all dependencies injected.

    Raises:
        MerchantNotFoundError: If credentials are missing and bootstrap fails.
        OAuthInitialTokenError: If initial token acquisition fails.
        ReportJobFailedError: If the report job enters FAILED state.
        ReportJobCancelledError: If the report job enters CANCELLED state.
        ReportPollingExhaustedError: If polling exhausts max retries.
        BronzeWriteError: If S3 write fails.
        OtterAPIError: If the Otter API returns an unexpected error.
    """
    from zoneinfo import ZoneInfo

    merchant_id = run_ctx.merchant_id
    secrets = run_ctx.secrets
    logs = run_ctx.logs
    otter = run_ctx.otter
    bronze = run_ctx.bronze
    oauth = run_ctx.oauth

    # ── Step 1: Load or bootstrap credentials ──────────────────────────────
    try:
        creds = secrets.load(merchant_id)  # type: ignore[union-attr]
    except MerchantNotFoundError:
        # Auto-bootstrap: PR2 would validate credentials come from a secure bootstrap channel
        # PR1: use client_id/client_secret from environment variables OTTER_CLIENT_ID/OTTER_CLIENT_SECRET
        import os

        client_id = os.environ.get("OTTER_CLIENT_ID", "")
        client_secret = os.environ.get("OTTER_CLIENT_SECRET", "")
        assert oauth is not None
        creds = oauth.request_initial_token(
            merchant_id,
            client_id=client_id or None,
            client_secret=client_secret or None,
        )

    # ── Step 2: Insert STARTED log row ────────────────────────────────────
    log_row = RunLog(
        id=run_ctx.run_id,
        merchant_id=merchant_id,
        run_id=run_ctx.run_id,
        pipeline_name="otter_bronze_ingestion",
        status="STARTED",
        started_at=run_ctx.run_timestamp_utc,
    )
    try:
        logs.insert_started(log_row)  # type: ignore[union-attr]
    except Exception:
        # Best-effort logging — if this fails, proceed anyway (PR2 will make this hard)
        pass

    try:
        import json

        # ── Step 3: Compute T-1 window ─────────────────────────────────────
        store_tz_str = getattr(creds, "store_tz", "America/New_York")
        store_tz = ZoneInfo(store_tz_str)
        now_utc = datetime.now(UTC)
        t1_start, t1_end = compute_t1_window(store_tz, now_utc)

        # ── Step 4: Fetch and write orders ────────────────────────────────
        assert otter is not None
        orders_data = otter.fetch_orders(
            store_id=merchant_id,
            start_utc=t1_start,
            end_utc=t1_end,
        )
        assert bronze is not None

        bronze.write_raw(
            merchant_id=merchant_id,
            endpoint="orders",
            payload=json.dumps(orders_data),
            run_timestamp_utc=run_ctx.run_timestamp_utc,
        )

        # ── Step 5: Request report job ────────────────────────────────────
        report_body = {
            "store_id": merchant_id,
            "period_start": t1_start.isoformat(),
            "period_end": t1_end.isoformat(),
            "report_type": "daily_summary",
        }
        job_id = otter.request_report(merchant_id, report_body)
        enqueue_payload = {"jobId": job_id}
        bronze.write_raw(
            merchant_id=merchant_id,
            endpoint="reports_enqueue",
            payload=json.dumps(enqueue_payload),
            run_timestamp_utc=run_ctx.run_timestamp_utc,
        )

        # ── Step 6: Poll until READY ──────────────────────────────────────
        result_data = poll_report_until_ready(
            otter,
            merchant_id,
            job_id,
            run_ctx.report_poll_policy,  # type: ignore[arg-type]
            clock=lambda: datetime.now(UTC),
        )
        bronze.write_raw(
            merchant_id=merchant_id,
            endpoint="reports_result",
            payload=json.dumps(result_data),
            run_timestamp_utc=run_ctx.run_timestamp_utc,
        )

        # ── Step 7: Mark SUCCESS ──────────────────────────────────────────
        logs.update_finished(  # type: ignore[union-attr]
            run_ctx.run_id,
            status="SUCCESS",
            error_class=None,
            error_message=None,
        )

    except Exception as exc:
        # Always update log to FAILED before re-raising
        logs.update_finished(  # type: ignore[union-attr]
            run_ctx.run_id,
            status="FAILED",
            error_class=type(exc).__name__,
            error_message=str(exc),
        )
        raise


# ---------------------------------------------------------------------------
# Internal: build dependencies (factored for testability)
# ---------------------------------------------------------------------------


def _build_deps(
    merchant_id: str,
    env: Literal["dev", "staging", "prod"],
    *,
    secrets: InMemorySecrets,
    logs: InMemoryLogs,
    s3_client: Any,
) -> tuple[
    InMemorySecrets,
    InMemoryLogs,
    OAuthRefresher,
    OtterClient,
    BronzeWriter,
    RunContext,
]:
    """Build all dependencies for the ingestion run.

    In PR1, real boto3 S3 client, real InMemorySecrets/Logs, real
    OAuthRefresher/OtterClient are used. PR2 will swap InMemorySecrets
    for KMS-backed and InMemoryLogs for Postgres-backed.

    Returns:
        A tuple of (secrets, logs, oauth, otter, bronze, run_ctx).
    """
    session = requests.Session()

    oauth = OAuthRefresher(session=session, secrets=secrets)

    bronze = BronzeWriter(
        s3_client=s3_client,
        bucket_name=f"ofae-data-lakehouse-bronze-{env}",
    )

    # Build a temporary RunContext to extract policies and run_id
    # (we need otter first, so we build it in two passes)
    def clock() -> datetime:
        return datetime.now(UTC)

    rate_limit_policy = RetryPolicy(
        max_retries=3, base_seconds=1.0, cap_seconds=8.0, jitter=True
    )
    transient_401_policy = RetryPolicy(
        max_retries=1, base_seconds=0.5, cap_seconds=1.0, jitter=True
    )
    report_poll_policy = RetryPolicy(
        max_retries=10, base_seconds=2.0, cap_seconds=60.0, jitter=True
    )

    run_id = uuid4()
    from datetime import UTC as _UTC

    bucket_name = f"ofae-data-lakehouse-bronze-{env}"

    # Build otter with the temp context
    otter = OtterClient(
        session=session,
        secrets=secrets,
        oauth_refresher=oauth,
        clock=clock,
        rate_limit_policy=rate_limit_policy,
        transient_401_policy=transient_401_policy,
        run_id=run_id,
    )

    run_ctx = RunContext(
        run_id=run_id,
        merchant_id=merchant_id,
        env=env,
        bucket_name=bucket_name,
        run_timestamp_utc=datetime.now(_UTC),
        s3_client=s3_client,
        secrets=secrets,
        logs=logs,
        oauth=oauth,
        otter=otter,
        bronze=bronze,
        rate_limit_policy=rate_limit_policy,
        transient_401_policy=transient_401_policy,
        report_poll_policy=report_poll_policy,
    )

    return secrets, logs, oauth, otter, bronze, run_ctx


# ---------------------------------------------------------------------------
# Click CLI
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """omc-analytics Bronze ingestion CLI."""
    pass


@cli.command("run-bronze")
@click.option(
    "--merchant-id",
    required=True,
    type=str,
    help="The merchant/store identifier.",
)
@click.option(
    "--env",
    required=True,
    type=click.Choice(["dev", "staging", "prod"]),
    help="Target environment.",
)
def run_bronze(merchant_id: str, env: str) -> None:
    """Run the Bronze ingestion pipeline for a merchant."""
    assert env in (
        "dev",
        "staging",
        "prod",
    ), f"env must be one of dev|staging|prod, got {env!r}"
    secrets: InMemorySecrets = InMemorySecrets()
    logs: InMemoryLogs = InMemoryLogs()
    s3_client = boto3.client("s3", region_name="us-east-1")

    _secrets, _logs, _oauth, _otter, _bronze, run_ctx = _build_deps(
        merchant_id=merchant_id,
        env=env,  # type: ignore[arg-type]
        secrets=secrets,
        logs=logs,
        s3_client=s3_client,
    )

    run_bronze_impl(run_ctx)
    click.echo(f"Bronze ingestion complete for merchant {merchant_id}.")


if __name__ == "__main__":
    cli()
