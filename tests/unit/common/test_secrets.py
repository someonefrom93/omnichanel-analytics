"""Tests for SecretsPort Protocol and InMemorySecrets implementation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from omc_analytics.common.secrets import (
    InMemorySecrets,
    MerchantCredentials,
    MerchantNotFoundError,
    SecretsPort,
)


class TestMerchantCredentials:
    """Test MerchantCredentials pydantic model validation."""

    def test_valid_credentials_all_fields(self) -> None:
        """All fields accepted when valid."""
        creds = MerchantCredentials(
            merchant_id="merchant_001",
            public_api_url="https://api.otter.dev",
            client_id="client-id-123",
            client_secret_encrypted="secret-xyz",
            access_token="token-abc",
            refresh_token="refresh-xyz",
            expires_at=datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC),
        )
        assert creds.merchant_id == "merchant_001"
        assert str(creds.public_api_url) == "https://api.otter.dev/"
        assert creds.access_token == "token-abc"
        assert creds.refresh_token == "refresh-xyz"

    def test_valid_credentials_only_required(self) -> None:
        """Only required fields — optional ones may be None."""
        creds = MerchantCredentials(
            merchant_id="merchant_001",
            public_api_url="https://api.otter.dev",
            client_id="client-id-123",
            client_secret_encrypted="secret-xyz",
        )
        assert creds.access_token is None
        assert creds.refresh_token is None
        assert creds.expires_at is None

    def test_rejects_bad_merchant_id_empty(self) -> None:
        """Empty merchant_id is rejected."""
        with pytest.raises(ValidationError):
            MerchantCredentials(
                merchant_id="",
                public_api_url="https://api.otter.dev",
                client_id="client-id-123",
                client_secret_encrypted="secret-xyz",
            )

    def test_rejects_bad_public_api_url(self) -> None:
        """Invalid public_api_url is rejected."""
        with pytest.raises(ValidationError):
            MerchantCredentials(
                merchant_id="merchant_001",
                public_api_url="not-a-url",
                client_id="client-id-123",
                client_secret_encrypted="secret-xyz",
            )


class TestSecretsPortProtocol:
    """Test SecretsPort Protocol interface."""

    def test_load_returns_saved_credentials(self) -> None:
        """load returns the same credentials passed to save."""
        store: dict[str, MerchantCredentials] = {}
        impl = InMemorySecrets(store)
        creds = MerchantCredentials(
            merchant_id="merchant_001",
            public_api_url="https://api.otter.dev",
            client_id="client-id-123",
            client_secret_encrypted="secret-xyz",
            access_token="token-abc",
            expires_at=datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC),
        )
        impl.save(creds)
        loaded = impl.load("merchant_001")
        assert loaded.merchant_id == "merchant_001"
        assert loaded.access_token == "token-abc"

    def test_load_raises_merchant_not_found_error(self) -> None:
        """load raises MerchantNotFoundError for unknown merchant."""
        impl = InMemorySecrets({})
        with pytest.raises(MerchantNotFoundError):
            impl.load("unknown-merchant")

    def test_save_overwrites_existing_credentials(self) -> None:
        """save replaces previously stored credentials for same merchant_id."""
        store: dict[str, MerchantCredentials] = {}
        impl = InMemorySecrets(store)
        creds1 = MerchantCredentials(
            merchant_id="merchant_001",
            public_api_url="https://api.otter.dev",
            client_id="client-id-123",
            client_secret_encrypted="secret-xyz",
            access_token="token-v1",
        )
        creds2 = MerchantCredentials(
            merchant_id="merchant_001",
            public_api_url="https://api.otter.dev",
            client_id="client-id-123",
            client_secret_encrypted="secret-xyz",
            access_token="token-v2",
        )
        impl.save(creds1)
        impl.save(creds2)
        loaded = impl.load("merchant_001")
        assert loaded.access_token == "token-v2"

    def test_in_memory_secrets_seed_via_constructor(self) -> None:
        """InMemorySecrets can be pre-seeded via constructor dict."""
        creds = MerchantCredentials(
            merchant_id="merchant_001",
            public_api_url="https://api.otter.dev",
            client_id="client-id-123",
            client_secret_encrypted="secret-xyz",
            access_token="seeded-token",
        )
        pre_seeded = {creds.merchant_id: creds}
        impl = InMemorySecrets(pre_seeded)
        loaded = impl.load("merchant_001")
        assert loaded.access_token == "seeded-token"

    def test_protocol_load_signature(self) -> None:
        """SecretsPort.Protocol declares load(merchant_id: str) -> MerchantCredentials."""
        # This test verifies the Protocol interface exists and is structurally correct.
        # The Protocol is an ABC — we verify it has the right method signatures.
        import inspect

        sig = inspect.signature(SecretsPort.load)
        params = list(sig.parameters.keys())
        assert "merchant_id" in params

    def test_protocol_save_signature(self) -> None:
        """SecretsPort.Protocol declares save(creds: MerchantCredentials) -> None."""
        import inspect

        sig = inspect.signature(SecretsPort.save)
        params = list(sig.parameters.keys())
        assert "creds" in params
