"""RunContext — configuration and dependency injection for a single ingestion run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from omc_analytics.common.logs import LogsPort
from omc_analytics.common.secrets import SecretsPort
from omc_analytics.ingestion.backoff import RetryPolicy
from omc_analytics.ingestion.bronze_writer import BronzeWriter
from omc_analytics.ingestion.oauth import OAuthRefresher
from omc_analytics.ingestion.otter_client import OtterClient

# In PR1 we use InMemorySecrets; PR2 swaps to KMS-backed impl
# In PR1 we use InMemoryLogs; PR2 swaps to Postgres-backed impl


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
    s3_client: Any = field(default=None, repr=False)
    secrets: SecretsPort | None = field(default=None, repr=False)
    logs: LogsPort | None = field(default=None, repr=False)
    oauth: OAuthRefresher | None = field(default=None, repr=False)
    otter: OtterClient | None = field(default=None, repr=False)
    bronze: BronzeWriter | None = field(default=None, repr=False)
    rate_limit_policy: RetryPolicy | None = field(default=None, repr=False)
    transient_401_policy: RetryPolicy | None = field(default=None, repr=False)
    report_poll_policy: RetryPolicy | None = field(default=None, repr=False)


_ENV_BUCKET_MAP: dict[str, str] = {
    "dev": "ofae-data-lakehouse-bronze-dev",
    "staging": "ofae-data-lakehouse-bronze-staging",
    "prod": "ofae-data-lakehouse-bronze-prod",
}


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

    from datetime import UTC
    from uuid import uuid4

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
