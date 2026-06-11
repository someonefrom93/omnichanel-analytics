"""RunContext — configuration and dependency injection for a single ingestion run."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from omc_analytics.common.logs import LogsPort
from omc_analytics.common.secrets import SecretsPort
from omc_analytics.ingestion.backoff import RetryPolicy
from omc_analytics.ingestion.bronze_writer import BronzeWriter
from omc_analytics.ingestion.oauth import OAuthRefresher
from omc_analytics.ingestion.otter_client import OtterClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """Raised when a required configuration variable is missing or invalid.

    Attributes:
        name: The name of the missing/invalid environment variable.
        reason: Human-readable explanation of the error.
    """

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason
        super().__init__(f"ConfigError({name}): {reason}")


# ---------------------------------------------------------------------------
# RunContext
# ---------------------------------------------------------------------------


@dataclass
class RunContext:
    """Container for all dependencies and configuration for one ingestion run.

    This is a plain dataclass (not a Pydantic model) because several
    dependencies are Protocol types that cannot be used with pydantic
    isinstance checks. The s3_client is typed as Any because boto3 clients
    are not pydantic-serializable.
    """

    run_id: Any  # uuid.UUID — typed as Any to avoid circular import
    merchant_id: str
    env: Literal["dev", "staging", "prod"]
    bucket_name: str
    run_timestamp_utc: datetime
    # Backend selection
    secrets_backend: str = "memory"
    logs_backend: str = "memory"
    kms_key_id: str | None = None
    pg_dsn: str | None = None
    aws_region: str = "us-east-1"
    # Resolved implementations (set by factories)
    s3_client: Any = field(default=None, repr=False)
    secrets: SecretsPort | None = field(default=None, repr=False)
    logs: LogsPort | None = field(default=None, repr=False)
    oauth: OAuthRefresher | None = field(default=None, repr=False)
    otter: OtterClient | None = field(default=None, repr=False)
    bronze: BronzeWriter | None = field(default=None, repr=False)
    rate_limit_policy: RetryPolicy | None = field(default=None, repr=False)
    transient_401_policy: RetryPolicy | None = field(default=None, repr=False)
    report_poll_policy: RetryPolicy | None = field(default=None, repr=False)
    # Backfill configuration
    backfill: bool = False
    backfill_days: int = 30

    def __post_init__(self) -> None:
        """Validate backfill_days range when backfill is enabled."""
        if self.backfill and not 1 <= self.backfill_days <= 90:
            raise ValueError(
                f"backfill_days must be between 1 and 90 when backfill=True, "
                f"got {self.backfill_days}"
            )


_ENV_BUCKET_MAP: dict[str, str] = {
    "dev": "ofae-data-lakehouse-bronze-dev",
    "staging": "ofae-data-lakehouse-bronze-staging",
    "prod": "ofae-data-lakehouse-bronze-prod",
}

# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _read_env_defaults() -> dict[str, str]:
    """Read OMCAE_* environment variables with defaults."""
    return {
        "secrets_backend": os.environ.get("OMCAE_SECRETS_BACKEND", "memory"),
        "logs_backend": os.environ.get("OMCAE_LOGS_BACKEND", "memory"),
        "kms_key_id": os.environ.get("OMCAE_KMS_KEY_ID", ""),
        "pg_dsn": os.environ.get("OMCAE_PG_DSN", ""),
        "aws_region": os.environ.get("OMCAE_AWS_REGION", "us-east-1"),
    }


def _has_aws_credentials() -> bool:
    """Check if AWS credentials are available in the environment."""
    has_key_id = bool(os.environ.get("AWS_ACCESS_KEY_ID"))
    has_secret = bool(os.environ.get("AWS_SECRET_ACCESS_KEY"))
    return has_key_id and has_secret


def secrets_factory(
    ctx: RunContext,
    kms_client: Any = None,
    blob_store: Any = None,
) -> SecretsPort:
    """Factory that returns the appropriate SecretsPort implementation.

    Args:
        ctx: RunContext with backend selection fields.
        kms_client: boto3 KMS client (required when secrets_backend is "kms").
        blob_store: BlobStore implementation (required when secrets_backend is "kms").

    Returns:
        InMemorySecrets (default dev mode) or KMSSecrets (production).

    Raises:
        ConfigError: If secrets_backend is "kms" but OMCAE_KMS_KEY_ID is missing.
    """
    backend = ctx.secrets_backend

    if backend == "memory":
        return _build_inmemory_secrets(ctx)

    if backend == "kms":
        return _build_kms_secrets(ctx, kms_client, blob_store)

    raise ConfigError(
        name="OMCAE_SECRETS_BACKEND",
        reason=f"unknown backend {backend!r}; allowed: memory, kms",
    )


def _build_inmemory_secrets(ctx: RunContext) -> SecretsPort:
    """Build InMemorySecrets (dev path)."""
    from omc_analytics.common.secrets import InMemorySecrets

    return InMemorySecrets()


def _build_kms_secrets(
    ctx: RunContext,
    kms_client: Any,
    blob_store: Any,
) -> SecretsPort:
    """Build KMSSecrets or fall back to InMemorySecrets if no AWS credentials."""
    from omc_analytics.common.kms_secrets import KMSSecrets
    from omc_analytics.common.secrets import InMemorySecrets

    if not ctx.kms_key_id:
        raise ConfigError(
            name="OMCAE_KMS_KEY_ID",
            reason="OMCAE_SECRETS_BACKEND=kms requires OMCAE_KMS_KEY_ID to be set",
        )

    if kms_client is None or not _has_aws_credentials():
        # Dev-mode fallback: no AWS credentials available
        logger.debug(
            "KMSSecrets requested but no AWS credentials found; "
            "using InMemorySecrets (dev mode)"
        )
        return InMemorySecrets()

    return KMSSecrets(
        kms_client=kms_client,
        blob_store=blob_store,
        kms_key_id=ctx.kms_key_id,
    )


def logs_factory(
    ctx: RunContext,
    connection_factory: Any = None,
) -> LogsPort:
    """Factory that returns the appropriate LogsPort implementation.

    Args:
        ctx: RunContext with backend selection fields.
        connection_factory: Callable returning a psycopg2 connection
            (required when logs_backend is "postgres").

    Returns:
        InMemoryLogs (default), SQLiteLogs, or PostgresLogs.

    Raises:
        ConfigError: If logs_backend is "postgres" but OMCAE_PG_DSN is missing.
    """
    backend = ctx.logs_backend

    if backend == "memory":
        return _build_inmemory_logs(ctx)

    if backend == "sqlite":
        return _build_sqlite_logs(ctx)

    if backend == "postgres":
        return _build_postgres_logs(ctx, connection_factory)

    raise ConfigError(
        name="OMCAE_LOGS_BACKEND",
        reason=f"unknown backend {backend!r}; allowed: memory, sqlite, postgres",
    )


def _build_inmemory_logs(ctx: RunContext) -> LogsPort:
    """Build InMemoryLogs (dev path)."""
    from omc_analytics.common.logs import InMemoryLogs

    return InMemoryLogs()


def _build_sqlite_logs(ctx: RunContext) -> LogsPort:
    """Build SQLiteLogs (file-based local dev path)."""
    from omc_analytics.common.sqlite_logs import SQLiteLogs

    return SQLiteLogs()


def _build_postgres_logs(
    ctx: RunContext,
    connection_factory: Any,
) -> LogsPort:
    """Build PostgresLogs (production path)."""
    from omc_analytics.common.postgres_logs import PostgresLogs

    if not ctx.pg_dsn:
        raise ConfigError(
            name="OMCAE_PG_DSN",
            reason="OMCAE_LOGS_BACKEND=postgres requires OMCAE_PG_DSN to be set",
        )

    if connection_factory is None:
        raise ConfigError(
            name="OMCAE_PG_DSN",
            reason="OMCAE_LOGS_BACKEND=postgres requires a connection factory",
        )

    return PostgresLogs(connection_factory=connection_factory)


# ---------------------------------------------------------------------------
# Main context builder
# ---------------------------------------------------------------------------


def build_run_context(
    merchant_id: str,
    env: Literal["dev", "staging", "prod"],
    *,
    secrets: SecretsPort,
    logs: LogsPort,
    oauth: OAuthRefresher,
    otter: OtterClient,
    bronze: BronzeWriter,
    s3_client: Any,
) -> RunContext:
    """Factory to build a RunContext with all dependencies wired.

    Args:
        merchant_id: The merchant/store identifier.
        env: One of "dev", "staging", "prod".
        secrets: SecretsPort implementation (InMemorySecrets in PR1).
        logs: LogsPort implementation (InMemoryLogs in PR1).
        oauth: Configured OAuthRefresher instance.
        otter: Configured OtterClient instance.
        bronze: Configured BronzeWriter instance.
        s3_client: boto3 S3 client (real or moto stubbed).

    Returns:
        A fully-populated RunContext.

    Raises:
        ValueError: If env is not one of the known values.
    """
    if env not in _ENV_BUCKET_MAP:
        msg = f"env must be one of {sorted(_ENV_BUCKET_MAP.keys())}, got {env!r}"
        raise ValueError(msg)

    # Read backend configuration from environment
    env_defaults = _read_env_defaults()

    run_id = uuid4()  # generate a fresh UUID
    run_timestamp_utc = datetime.now(UTC)
    bucket_name = _ENV_BUCKET_MAP[env]

    rate_limit_policy = RetryPolicy(
        max_retries=3,
        base_seconds=1.0,
        cap_seconds=8.0,
        jitter=True,
    )
    transient_401_policy = RetryPolicy(
        max_retries=1,
        base_seconds=0.5,
        cap_seconds=1.0,
        jitter=True,
    )
    report_poll_policy = RetryPolicy(
        max_retries=10,
        base_seconds=2.0,
        cap_seconds=60.0,
        jitter=True,
    )

    return RunContext(
        run_id=run_id,
        merchant_id=merchant_id,
        env=env,
        bucket_name=bucket_name,
        run_timestamp_utc=run_timestamp_utc,
        secrets_backend=env_defaults["secrets_backend"],
        logs_backend=env_defaults["logs_backend"],
        kms_key_id=env_defaults["kms_key_id"] or None,
        pg_dsn=env_defaults["pg_dsn"] or None,
        aws_region=env_defaults["aws_region"],
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
