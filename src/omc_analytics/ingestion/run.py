"""ingestion/run.py — CLI orchestration for the Bronze ingestion pipeline.

PR1 uses InMemorySecrets and InMemoryLogs stubs.
PR2 swaps these for KMS-backed secrets and Postgres-backed logs.

OMCAE_* environment variables (documented in click help):
    OMCAE_SECRETS_BACKEND   — memory (default) | kms
    OMCAE_LOGS_BACKEND     — memory (default) | sqlite | postgres
    OMCAE_KMS_KEY_ID       — required when SECRETS_BACKEND=kms
    OMCAE_PG_DSN           — required when LOGS_BACKEND=postgres
    OMCAE_AWS_REGION       — default us-east-1 (used for boto3 clients)
"""

from __future__ import annotations

import time
import zoneinfo
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

import boto3
import click
import requests

from omc_analytics.common.config import (
    RunContext,
    _read_env_defaults,
    logs_factory,
    secrets_factory,
)
from omc_analytics.common.logs import LogsPort, RunLog
from omc_analytics.common.secrets import (
    MerchantNotFoundError,
    SecretsPort,
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
from omc_analytics.transformation.cli import silver_group

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def compute_window_for_date(
    target_date: date,
    store_tz: zoneinfo.ZoneInfo,
) -> tuple[datetime, datetime]:
    """Compute the ingestion window for an arbitrary target date in a store timezone.

    Args:
        target_date: The calendar date (in the store's local timezone) to compute
            the window for.
        store_tz: A ZoneInfo for the store's local timezone.

    Returns:
        A tuple (start_utc, end_utc) where:
        - start_utc is target_date 00:00:00 in store_tz, converted to UTC
        - end_utc is target_date 23:59:59.999999 in store_tz, converted to UTC

    Pure function: no clock, no I/O.
    """
    start_local = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        0,
        0,
        0,
        0,
        tzinfo=store_tz,
    )
    end_local = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        23,
        59,
        59,
        999999,
        tzinfo=store_tz,
    )
    return (start_local.astimezone(UTC), end_local.astimezone(UTC))


def compute_t1_window(
    store_tz: zoneinfo.ZoneInfo,
    now_utc: datetime,
) -> tuple[datetime, datetime]:
    """Compute the T-1 (yesterday) ingestion window in UTC for a store's local timezone.

    Args:
        store_tz: A ZoneInfo for the store's local timezone.
        now_utc: The current time in UTC.

    Returns:
        A tuple (window_start_utc, window_end_utc) representing the
        T-1 day in the store's local timezone, expressed as UTC datetimes.
    """
    yesterday = (now_utc.astimezone(store_tz) - timedelta(days=1)).date()
    return compute_window_for_date(yesterday, store_tz)


def compute_backfill_dates(
    days: int,
    now_utc: datetime,
) -> list[date]:
    """Return the dates to backfill, ordered oldest-first.

    [now_utc.date() - timedelta(days=N), ..., now_utc.date() - timedelta(days=1)]
    Excludes today (a T-1-style run already covers today once it lands).
    Excludes dates further back than `days`.

    Args:
        days: Number of backfill days. Must be in [1, 90].
        now_utc: The current time in UTC.

    Returns:
        A list of date objects, oldest-first.

    Raises:
        ValueError: If days is not in [1, 90].
    """
    if not 1 <= days <= 90:
        raise ValueError(f"days must be in [1, 90], got {days}")
    return [(now_utc.date() - timedelta(days=i)) for i in range(days, 0, -1)]


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


def run_bronze_impl(
    run_ctx: RunContext,
    *,
    run_id_override: UUID | None = None,
    run_timestamp_override: datetime | None = None,
    target_date: date | None = None,
) -> None:
    """Pure orchestration logic for one Bronze ingestion run.

    Args:
        run_ctx: A fully-populated RunContext with all dependencies injected.
        run_id_override: If provided, use this UUID as the run_id for this iteration
            instead of the run_ctx.run_id.
        run_timestamp_override: If provided, use this datetime as run_timestamp_utc
            for this iteration instead of datetime.now(UTC).
        target_date: If provided, use this date for the Bronze partition path
            (order/ingestion date) instead of T-1 computed from store timezone.

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

    # ── Compute effective values from overrides or defaults ──────────────────
    effective_run_id = (
        run_id_override if run_id_override is not None else run_ctx.run_id
    )
    effective_run_timestamp_utc = (
        run_timestamp_override
        if run_timestamp_override is not None
        else run_ctx.run_timestamp_utc
    )
    effective_target_date: date
    if target_date is not None:
        effective_target_date = target_date
    else:
        # Default: T-1 behavior (unchanged from PR2a)
        store_tz_str = "America/New_York"  # will be overridden by creds
        now_utc = datetime.now(UTC)
        # We compute the store_tz after loading creds below
        effective_target_date = (now_utc - timedelta(days=1)).date()

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
        id=effective_run_id,
        merchant_id=merchant_id,
        run_id=effective_run_id,
        pipeline_name="otter_bronze_ingestion",
        status="STARTED",
        started_at=effective_run_timestamp_utc,
    )
    try:
        logs.insert_started(log_row)  # type: ignore[union-attr]
    except Exception:
        # Best-effort logging — if this fails, proceed anyway (PR2 will make this hard)
        pass

    try:
        import json

        # ── Step 3: Compute window from effective_target_date ───────────────
        store_tz_str = getattr(creds, "store_tz", "America/New_York")
        store_tz = ZoneInfo(store_tz_str)
        if target_date is not None:
            # Override path: use the provided target_date directly
            window_start, window_end = compute_window_for_date(target_date, store_tz)
        else:
            # T-1 path (default): same as PR2a behavior
            now_utc = datetime.now(UTC)
            window_start, window_end = compute_t1_window(store_tz, now_utc)
            effective_target_date = window_start.date()

        # ── Step 4: Fetch and write orders ────────────────────────────────
        assert otter is not None
        orders_data = otter.fetch_orders(
            store_id=merchant_id,
            start_utc=window_start,
            end_utc=window_end,
        )
        assert bronze is not None

        bronze.write_raw(
            merchant_id=merchant_id,
            endpoint="orders",
            payload=json.dumps(orders_data),
            target_date=effective_target_date,
            run_timestamp_utc=effective_run_timestamp_utc,
        )

        # ── Step 5: Request report job ────────────────────────────────────
        report_body = {
            "store_id": merchant_id,
            "period_start": window_start.isoformat(),
            "period_end": window_end.isoformat(),
            "report_type": "daily_summary",
        }
        job_id = otter.request_report(merchant_id, report_body)
        enqueue_payload = {"jobId": job_id}
        bronze.write_raw(
            merchant_id=merchant_id,
            endpoint="reports_enqueue",
            payload=json.dumps(enqueue_payload),
            target_date=effective_target_date,
            run_timestamp_utc=effective_run_timestamp_utc,
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
            target_date=effective_target_date,
            run_timestamp_utc=effective_run_timestamp_utc,
        )

        # ── Step 7: Mark SUCCESS ──────────────────────────────────────────
        logs.update_finished(  # type: ignore[union-attr]
            effective_run_id,
            status="SUCCESS",
            error_class=None,
            error_message=None,
        )

    except Exception as exc:
        # Always update log to FAILED before re-raising
        logs.update_finished(  # type: ignore[union-attr]
            effective_run_id,
            status="FAILED",
            error_class=type(exc).__name__,
            error_message=str(exc),
        )
        raise


def run_bronze_with_backfill(ctx: RunContext) -> int:
    """Run the Bronze ingestion for each day in the backfill window.

    Per-iteration:
    - Fresh run_id (uuid4)
    - Fresh run_timestamp_utc (datetime.now(UTC))
    - target_date from compute_backfill_dates(...)

    Fail-soft: each iteration is independent. On exception, write a FAILED
    log row with error_class and error_message, then continue.

    Returns 0 if all iterations succeeded; 1 if any failed.
    The caller (CLI) should propagate this exit code to the OS.
    """
    if not ctx.backfill:
        # backfill=False: run once with T-1 behavior (same as run_bronze_impl)
        run_bronze_impl(ctx)
        return 0

    dates = compute_backfill_dates(ctx.backfill_days, datetime.now(UTC))
    any_failed = False

    for target_date in dates:
        # Fresh per-iteration run_id and timestamp
        per_iter_run_id = uuid4()
        per_iter_timestamp = datetime.now(UTC)

        try:
            run_bronze_impl(
                ctx,
                run_id_override=per_iter_run_id,
                run_timestamp_override=per_iter_timestamp,
                target_date=target_date,
            )
        except Exception:
            any_failed = True
            # run_bronze_impl already wrote a FAILED log via update_finished
            # before re-raising. Do NOT write another FAILED log here —
            # that would create a duplicate for the same run_id.
            # Just continue to the next day (fail-soft contract).
            continue

    return 1 if any_failed else 0


# ---------------------------------------------------------------------------
# Internal: build dependencies (factored for testability)
# ---------------------------------------------------------------------------


def _build_deps(
    merchant_id: str,
    env: Literal["dev", "staging", "prod"],
    *,
    secrets: SecretsPort,
    logs: LogsPort,
    s3_client: Any,
    backfill: bool = False,
    backfill_days: int = 30,
) -> tuple[
    SecretsPort,
    LogsPort,
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
        backfill=backfill,
        backfill_days=backfill_days,
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
@click.option(
    "--backfill / --no-backfill",
    default=False,
    help="Run a 30-day (or N-day) backfill instead of the single T-1 run.",
)
@click.option(
    "--backfill-days",
    type=click.IntRange(1, 90),
    default=30,
    show_default=True,
    help="Number of days to backfill (1-90). Only used when --backfill is set.",
)
def run_bronze(
    merchant_id: str,
    env: str,
    backfill: bool,
    backfill_days: int,
) -> None:
    """Run the Bronze ingestion pipeline for a merchant.

       Backend selection is controlled by environment variables (no new flags;
       all configuration is through OMCAE_* env vars read transparently):

       \b
    - OMCAE_SECRETS_BACKEND  memory (default) | kms
       - OMCAE_LOGS_BACKEND    memory (default) | sqlite | postgres
       - OMCAE_KMS_KEY_ID      required when SECRETS_BACKEND=kms
       - OMCAE_PG_DSN          required when LOGS_BACKEND=postgres
       - OMCAE_AWS_REGION      default us-east-1
    """
    import sys

    assert env in (
        "dev",
        "staging",
        "prod",
    ), f"env must be one of dev|staging|prod, got {env!r}"

    # Read backend configuration from environment
    env_defaults = _read_env_defaults()
    aws_region = env_defaults["aws_region"]

    # Build RunContext with backend fields set from env vars
    run_ctx = RunContext(
        run_id=uuid4(),
        merchant_id=merchant_id,
        env=env,  # type: ignore[arg-type]
        bucket_name=f"ofae-data-lakehouse-bronze-{env}",
        run_timestamp_utc=datetime.now(UTC),
        secrets_backend=env_defaults["secrets_backend"],
        logs_backend=env_defaults["logs_backend"],
        kms_key_id=env_defaults["kms_key_id"] or None,
        pg_dsn=env_defaults["pg_dsn"] or None,
        aws_region=aws_region,
        backfill=backfill,
        backfill_days=backfill_days,
    )

    # Build S3 client (real boto3)
    s3_client = boto3.client("s3", region_name=aws_region)

    # Build KMS client if needed (only when secrets_backend=kms)
    kms_client = None
    if run_ctx.secrets_backend == "kms":
        kms_client = boto3.client("kms", region_name=aws_region)

    # Build blob store for KMS (in-memory for now; PostgresBlobStore is PR2b)
    blob_store = None
    if run_ctx.secrets_backend == "kms":
        from omc_analytics.common.kms_secrets import InMemoryBlobStore

        blob_store = InMemoryBlobStore()

    # Build connection factory for PostgresLogs (only when logs_backend=postgres)
    connection_factory = None
    if run_ctx.logs_backend == "postgres" and run_ctx.pg_dsn:
        import functools

        import psycopg2

        connection_factory = functools.partial(psycopg2.connect, dsn=run_ctx.pg_dsn)

    # Use factories to build the right implementations
    secrets = secrets_factory(run_ctx, kms_client=kms_client, blob_store=blob_store)
    logs = logs_factory(run_ctx, connection_factory=connection_factory)

    _secrets, _logs, _oauth, _otter, _bronze, run_ctx = _build_deps(
        merchant_id=merchant_id,
        env=env,  # type: ignore[arg-type]
        secrets=secrets,
        logs=logs,
        s3_client=s3_client,
        backfill=backfill,
        backfill_days=backfill_days,
    )

    if backfill:
        return_code = run_bronze_with_backfill(run_ctx)
        sys.exit(return_code)
    else:
        run_bronze_impl(run_ctx)
        click.echo(f"Bronze ingestion complete for merchant {merchant_id}.")
        sys.exit(0)


cli.add_command(silver_group)


if __name__ == "__main__":
    cli()
