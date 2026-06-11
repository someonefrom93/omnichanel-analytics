"""Unit tests for config factory — OMCAE_SECRETS_BACKEND and OMCAE_LOGS_BACKEND wiring.

Strict TDD: tests written first, implementation follows.
"""

from __future__ import annotations

import logging

import pytest

from omc_analytics.common.config import (
    ConfigError,
    RunContext,
    _read_env_defaults,
    logs_factory,
    secrets_factory,
)
from omc_analytics.common.logs import InMemoryLogs, PostgresLogs, SQLiteLogs
from omc_analytics.common.secrets import InMemorySecrets, KMSSecrets


class TestReadEnvDefaults:
    """Tests for _read_env_defaults helper."""

    def test_reads_all_omcae_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All OMCAE vars are read with correct defaults."""
        for var in (
            "OMCAE_SECRETS_BACKEND",
            "OMCAE_LOGS_BACKEND",
            "OMCAE_KMS_KEY_ID",
            "OMCAE_PG_DSN",
            "OMCAE_AWS_REGION",
        ):
            monkeypatch.delenv(var, raising=False)

        defaults = _read_env_defaults()
        assert defaults["secrets_backend"] == "memory"
        assert defaults["logs_backend"] == "memory"
        assert defaults["kms_key_id"] == ""
        assert defaults["pg_dsn"] == ""
        assert defaults["aws_region"] == "us-east-1"

    def test_reads_custom_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Custom env var values are read correctly."""
        monkeypatch.setenv("OMCAE_SECRETS_BACKEND", "kms")
        monkeypatch.setenv("OMCAE_LOGS_BACKEND", "postgres")
        monkeypatch.setenv("OMCAE_KMS_KEY_ID", "alias/my-key")
        monkeypatch.setenv("OMCAE_PG_DSN", "postgresql://user:pass@localhost/db")
        monkeypatch.setenv("OMCAE_AWS_REGION", "us-west-2")

        defaults = _read_env_defaults()
        assert defaults["secrets_backend"] == "kms"
        assert defaults["logs_backend"] == "postgres"
        assert defaults["kms_key_id"] == "alias/my-key"
        assert defaults["pg_dsn"] == "postgresql://user:pass@localhost/db"
        assert defaults["aws_region"] == "us-west-2"


class TestConfigFactory:
    """Tests for secrets_factory and logs_factory with env var backends."""

    def test_default_backends_are_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No OMCAE_* env vars set → secrets=InMemorySecrets, logs=InMemoryLogs."""
        for var in (
            "OMCAE_SECRETS_BACKEND",
            "OMCAE_LOGS_BACKEND",
            "OMCAE_KMS_KEY_ID",
            "OMCAE_PG_DSN",
            "OMCAE_AWS_REGION",
        ):
            monkeypatch.delenv(var, raising=False)

        ctx = RunContext(
            run_id="fake-uuid",
            merchant_id="test-merchant",
            env="dev",
            bucket_name="test-bucket",
            run_timestamp_utc=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            secrets_backend="memory",
            logs_backend="memory",
        )

        result_secrets = secrets_factory(ctx)
        result_logs = logs_factory(ctx)

        assert isinstance(result_secrets, InMemorySecrets)
        assert isinstance(result_logs, InMemoryLogs)

    def test_kms_backend_requires_kms_key_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OMCAE_SECRETS_BACKEND=kms without OMCAE_KMS_KEY_ID → ConfigError."""
        monkeypatch.setenv("OMCAE_SECRETS_BACKEND", "kms")
        monkeypatch.delenv("OMCAE_KMS_KEY_ID", raising=False)
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")

        ctx = RunContext(
            run_id="fake-uuid",
            merchant_id="test-merchant",
            env="dev",
            bucket_name="test-bucket",
            run_timestamp_utc=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            secrets_backend="kms",
            kms_key_id=None,
        )

        with pytest.raises(ConfigError) as exc_info:
            secrets_factory(ctx)

        assert "OMCAE_KMS_KEY_ID" in str(exc_info.value)

    def test_postgres_backend_requires_pg_dsn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OMCAE_LOGS_BACKEND=postgres without OMCAE_PG_DSN → ConfigError."""
        monkeypatch.setenv("OMCAE_LOGS_BACKEND", "postgres")
        monkeypatch.delenv("OMCAE_PG_DSN", raising=False)

        ctx = RunContext(
            run_id="fake-uuid",
            merchant_id="test-merchant",
            env="dev",
            bucket_name="test-bucket",
            run_timestamp_utc=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            logs_backend="postgres",
            pg_dsn=None,
        )

        with pytest.raises(ConfigError) as exc_info:
            logs_factory(ctx)

        assert "OMCAE_PG_DSN" in str(exc_info.value)

    def test_kms_backend_with_all_vars_returns_km_secrets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With all required vars → factory returns KMSSecrets (verify type)."""
        monkeypatch.setenv("OMCAE_SECRETS_BACKEND", "kms")
        monkeypatch.setenv("OMCAE_KMS_KEY_ID", "alias/test-key")
        monkeypatch.setenv("OMCAE_AWS_REGION", "us-east-1")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key-id")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")

        ctx = RunContext(
            run_id="fake-uuid",
            merchant_id="test-merchant",
            env="dev",
            bucket_name="test-bucket",
            run_timestamp_utc=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            secrets_backend="kms",
            kms_key_id="alias/test-key",
            aws_region="us-east-1",
        )

        mock_kms = object()
        mock_blob = object()

        result = secrets_factory(ctx, kms_client=mock_kms, blob_store=mock_blob)
        assert isinstance(result, KMSSecrets)

    def test_sqlite_backend_returns_sqlite_logs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OMCAE_LOGS_BACKEND=sqlite → factory returns SQLiteLogs."""
        monkeypatch.setenv("OMCAE_LOGS_BACKEND", "sqlite")

        ctx = RunContext(
            run_id="fake-uuid",
            merchant_id="test-merchant",
            env="dev",
            bucket_name="test-bucket",
            run_timestamp_utc=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            logs_backend="sqlite",
        )

        result = logs_factory(ctx)
        assert isinstance(result, SQLiteLogs)

    def test_postgres_backend_with_dsn_returns_postgres_logs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OMCAE_LOGS_BACKEND=postgres + OMCAE_PG_DSN → factory returns PostgresLogs."""
        monkeypatch.setenv("OMCAE_LOGS_BACKEND", "postgres")
        monkeypatch.setenv(
            "OMCAE_PG_DSN", "postgresql://fake-user:fake@localhost:5432/fake"
        )

        ctx = RunContext(
            run_id="fake-uuid",
            merchant_id="test-merchant",
            env="dev",
            bucket_name="test-bucket",
            run_timestamp_utc=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            logs_backend="postgres",
            pg_dsn="postgresql://fake-user:fake@localhost:5432/fake",
        )

        def fake_factory(*args: object, **kwargs: object) -> object:
            return object()

        result = logs_factory(ctx, connection_factory=fake_factory)
        assert isinstance(result, PostgresLogs)

    def test_kms_backend_without_aws_creds_falls_back_to_memory(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """OMCAE_SECRETS_BACKEND=kms + OMCAE_KMS_KEY_ID but no AWS creds → InMemorySecrets with warning."""
        monkeypatch.setenv("OMCAE_SECRETS_BACKEND", "kms")
        monkeypatch.setenv("OMCAE_KMS_KEY_ID", "alias/test-key")
        # Ensure no AWS creds
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.delenv("AWS_SECURITY_TOKEN", raising=False)
        monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)

        ctx = RunContext(
            run_id="fake-uuid",
            merchant_id="test-merchant",
            env="dev",
            bucket_name="test-bucket",
            run_timestamp_utc=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            secrets_backend="kms",
            kms_key_id="alias/test-key",
        )

        caplog.set_level(logging.DEBUG)
        result = secrets_factory(ctx, kms_client=None, blob_store=None)
        assert isinstance(result, InMemorySecrets)
        # Verify warning was logged about falling back to dev mode
        assert any(
            "InMemorySecrets" in record.message or "dev mode" in record.message.lower()
            for record in caplog.records
        )

    def test_invalid_backend_raises_config_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OMCAE_SECRETS_BACKEND=unknown → ConfigError."""
        monkeypatch.setenv("OMCAE_SECRETS_BACKEND", "unknown")

        ctx = RunContext(
            run_id="fake-uuid",
            merchant_id="test-merchant",
            env="dev",
            bucket_name="test-bucket",
            run_timestamp_utc=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            secrets_backend="unknown",
        )

        with pytest.raises(ConfigError) as exc_info:
            secrets_factory(ctx)

        assert "unknown" in str(exc_info.value).lower()

    def test_aws_region_default_is_us_east_1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OMCAE_SECRETS_BACKEND=kms + OMCAE_KMS_KEY_ID + no OMCAE_AWS_REGION → aws_region is us-east-1."""
        for var in (
            "OMCAE_SECRETS_BACKEND",
            "OMCAE_KMS_KEY_ID",
            "OMCAE_AWS_REGION",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
        ):
            monkeypatch.delenv(var, raising=False)

        monkeypatch.setenv("OMCAE_SECRETS_BACKEND", "kms")
        monkeypatch.setenv("OMCAE_KMS_KEY_ID", "alias/test-key")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key-id")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")

        defaults = _read_env_defaults()
        assert defaults["aws_region"] == "us-east-1"
