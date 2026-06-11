"""Tests for OAuthRefresher auth adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
import requests
import responses

from omc_analytics.common.secrets import (
    InMemorySecrets,
    MerchantCredentials,
)
from omc_analytics.ingestion.oauth import (
    OAuthInitialTokenError,
    OAuthRefresher,
    OAuthRefreshError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def in_memory_secrets() -> InMemorySecrets:
    """Provides an empty InMemorySecrets stub."""
    return InMemorySecrets()


@pytest.fixture
def secrets_with_creds(in_memory_secrets: InMemorySecrets) -> InMemorySecrets:
    """Provides InMemorySecrets pre-loaded with a token expiring in 1 hour."""
    creds = MerchantCredentials(
        merchant_id="merchant_001",
        public_api_url="https://api.otter.dev",
        client_id="dev-client-id",
        client_secret_encrypted="dev-client-secret",
        access_token="existing-token",
        refresh_token="existing-refresh-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    in_memory_secrets.save(creds)
    return in_memory_secrets


@pytest.fixture
def clock():
    """Provides a controllable clock for time-dependent tests."""
    return mock.Mock(return_value=datetime.now(UTC))


# ---------------------------------------------------------------------------
# ensure_fresh_token
# ---------------------------------------------------------------------------


class TestEnsureFreshToken:
    """Test suite for ensure_fresh_token behavior."""

    def test_returns_existing_token_when_not_close_to_expiry(
        self, secrets_with_creds, clock
    ):
        """When (expires_at - now) >= 10 minutes, no HTTP call is made."""
        with responses.RequestsMock() as rs:
            session = requests.Session()
            refresher = OAuthRefresher(
                session=session,
                secrets=secrets_with_creds,
                clock=clock,
            )

            token = refresher.ensure_fresh_token("merchant_001")

            assert token == "existing-token"
            assert len(rs.calls) == 0

    def test_triggers_refresh_when_within_10_minutes(self, secrets_with_creds, clock):
        """When (expires_at - now) < 10 minutes, a refresh call is made."""
        # Set expires_at to 5 minutes from now
        creds = secrets_with_creds.load("merchant_001")
        creds = creds.model_copy(
            update={"expires_at": datetime.now(UTC) + timedelta(minutes=5)}
        )
        secrets_with_creds.save(creds)

        # Mock the clock to return the same time so the gap is exactly 5 min
        now = datetime.now(UTC)
        clock.return_value = now

        with responses.RequestsMock() as rs:
            rs.add(
                rs.POST,
                "https://api.otter.dev/v1/auth/token",
                json={
                    "access_token": "new-access-token",
                    "expires_in": 3600,
                    "refresh_token": "new-refresh-token",
                    "token_type": "Bearer",
                },
                status=200,
            )

            session = requests.Session()
            refresher = OAuthRefresher(
                session=session, secrets=secrets_with_creds, clock=clock
            )

            token = refresher.ensure_fresh_token("merchant_001")

            assert token == "new-access-token"
            assert len(rs.calls) == 1
            assert rs.calls[0].request.method == "POST"


# ---------------------------------------------------------------------------
# _refresh
# ---------------------------------------------------------------------------


class TestRefresh:
    """Test suite for _refresh behavior."""

    def test_calls_correct_endpoint_with_form_body(self, secrets_with_creds, clock):
        """Refresh POST must use grant_type=refresh_token with correct form fields."""
        with responses.RequestsMock() as rs:
            rs.add(
                rs.POST,
                "https://api.otter.dev/v1/auth/token",
                json={
                    "access_token": "refreshed-token",
                    "expires_in": 3600,
                    "refresh_token": "refreshed-refresh",
                    "token_type": "Bearer",
                },
                status=200,
            )

            session = requests.Session()
            refresher = OAuthRefresher(
                session=session, secrets=secrets_with_creds, clock=clock
            )

            creds = secrets_with_creds.load("merchant_001")
            new_creds = refresher._refresh(creds)

            assert new_creds.access_token == "refreshed-token"
            req = rs.calls[0].request
            assert "grant_type=refresh_token" in req.body
            assert "client_id=dev-client-id" in req.body
            assert "refresh_token=existing-refresh-token" in req.body

    def test_persists_new_token_via_secrets_port(self, secrets_with_creds, clock):
        """After a successful refresh, secrets.save must be called with updated creds."""
        with responses.RequestsMock() as rs:
            rs.add(
                rs.POST,
                "https://api.otter.dev/v1/auth/token",
                json={
                    "access_token": "persist-token",
                    "expires_in": 7200,
                    "refresh_token": "persist-refresh",
                    "token_type": "Bearer",
                },
                status=200,
            )

            session = requests.Session()
            refresher = OAuthRefresher(
                session=session, secrets=secrets_with_creds, clock=clock
            )

            creds = secrets_with_creds.load("merchant_001")
            refresher._refresh(creds)

            saved = secrets_with_creds.load("merchant_001")
            assert saved.access_token == "persist-token"
            # expires_at should be approximately now + expires_in - 60s safety margin
            assert saved.expires_at is not None

    def test_uses_refreshed_refresh_token_if_rotated(self, secrets_with_creds, clock):
        """If Otter returns a new refresh_token, the new one is saved."""
        with responses.RequestsMock() as rs:
            rs.add(
                rs.POST,
                "https://api.otter.dev/v1/auth/token",
                json={
                    "access_token": "rotated-token",
                    "expires_in": 3600,
                    "refresh_token": "rotated-refresh-token",
                    "token_type": "Bearer",
                },
                status=200,
            )

            session = requests.Session()
            refresher = OAuthRefresher(
                session=session, secrets=secrets_with_creds, clock=clock
            )

            creds = secrets_with_creds.load("merchant_001")
            new_creds = refresher._refresh(creds)

            # The new creds returned should carry the new refresh token
            assert new_creds.refresh_token == "rotated-refresh-token"
            # And it should be persisted
            saved = secrets_with_creds.load("merchant_001")
            assert saved.refresh_token == "rotated-refresh-token"

    def test_keeps_old_refresh_token_if_not_rotated(self, secrets_with_creds, clock):
        """If Otter response omits refresh_token, the old one is preserved."""
        with responses.RequestsMock() as rs:
            rs.add(
                rs.POST,
                "https://api.otter.dev/v1/auth/token",
                json={
                    "access_token": "no-rotation-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
                status=200,
            )

            session = requests.Session()
            refresher = OAuthRefresher(
                session=session, secrets=secrets_with_creds, clock=clock
            )

            creds = secrets_with_creds.load("merchant_001")
            original_refresh = creds.refresh_token
            new_creds = refresher._refresh(creds)

            # refresh_token is preserved (set to None when not in response)
            assert new_creds.refresh_token == original_refresh
            saved = secrets_with_creds.load("merchant_001")
            assert saved.refresh_token == original_refresh

    def test_raises_on_non_200(self, secrets_with_creds, clock):
        """Non-200 responses raise OAuthRefreshError."""
        with responses.RequestsMock() as rs:
            rs.add(
                rs.POST,
                "https://api.otter.dev/v1/auth/token",
                status=401,
                body="invalid grant",
            )

            session = requests.Session()
            refresher = OAuthRefresher(
                session=session, secrets=secrets_with_creds, clock=clock
            )

            creds = secrets_with_creds.load("merchant_001")
            with pytest.raises(OAuthRefreshError):
                refresher._refresh(creds)

    def test_raises_on_500(self, secrets_with_creds, clock):
        """500 responses also raise OAuthRefreshError."""
        with responses.RequestsMock() as rs:
            rs.add(
                rs.POST,
                "https://api.otter.dev/v1/auth/token",
                status=500,
                body="server error",
            )

            session = requests.Session()
            refresher = OAuthRefresher(
                session=session, secrets=secrets_with_creds, clock=clock
            )

            creds = secrets_with_creds.load("merchant_001")
            with pytest.raises(OAuthRefreshError):
                refresher._refresh(creds)


# ---------------------------------------------------------------------------
# request_initial_token
# ---------------------------------------------------------------------------


class TestRequestInitialToken:
    """Test suite for request_initial_token (client_credentials grant)."""

    def test_uses_client_credentials_grant(self, in_memory_secrets, clock):
        """request_initial_token must use grant_type=client_credentials with secrets."""
        with responses.RequestsMock() as rs:
            rs.add(
                rs.POST,
                "https://api.otter.dev/v1/auth/token",
                json={
                    "access_token": "initial-token",
                    "expires_in": 3600,
                    "refresh_token": "initial-refresh",
                    "token_type": "Bearer",
                },
                status=200,
            )

            session = requests.Session()
            # Pre-load credentials into the secrets store
            creds = MerchantCredentials(
                merchant_id="merchant_new",
                public_api_url="https://api.otter.dev",
                client_id="new-client-id",
                client_secret_encrypted="new-client-secret",
            )
            in_memory_secrets.save(creds)

            refresher = OAuthRefresher(
                session=session, secrets=in_memory_secrets, clock=clock
            )

            new_creds = refresher.request_initial_token("merchant_new")

            req = rs.calls[0].request
            assert "grant_type=client_credentials" in req.body
            assert "client_id=new-client-id" in req.body
            assert "client_secret=new-client-secret" in req.body
            assert new_creds.access_token == "initial-token"

    def test_handles_missing_refresh_token_in_response(self, in_memory_secrets, clock):
        """When the response omits refresh_token, it is set to None."""
        with responses.RequestsMock() as rs:
            rs.add(
                rs.POST,
                "https://api.otter.dev/v1/auth/token",
                json={
                    "access_token": "no-refresh-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
                status=200,
            )

            session = requests.Session()
            creds = MerchantCredentials(
                merchant_id="merchant_no_refresh",
                public_api_url="https://api.otter.dev",
                client_id="client-id",
                client_secret_encrypted="client-secret",
            )
            in_memory_secrets.save(creds)

            refresher = OAuthRefresher(
                session=session, secrets=in_memory_secrets, clock=clock
            )

            new_creds = refresher.request_initial_token("merchant_no_refresh")

            assert new_creds.refresh_token is None
            assert new_creds.access_token == "no-refresh-token"

    def test_persists_initial_token_via_secrets_port(self, in_memory_secrets, clock):
        """request_initial_token must save the new credentials to SecretsPort."""
        with responses.RequestsMock() as rs:
            rs.add(
                rs.POST,
                "https://api.otter.dev/v1/auth/token",
                json={
                    "access_token": "saved-initial-token",
                    "expires_in": 7200,
                    "refresh_token": "saved-refresh",
                    "token_type": "Bearer",
                },
                status=200,
            )

            session = requests.Session()
            creds = MerchantCredentials(
                merchant_id="merchant_save_test",
                public_api_url="https://api.otter.dev",
                client_id="client-id",
                client_secret_encrypted="client-secret",
            )
            in_memory_secrets.save(creds)

            refresher = OAuthRefresher(
                session=session, secrets=in_memory_secrets, clock=clock
            )

            refresher.request_initial_token("merchant_save_test")

            saved = in_memory_secrets.load("merchant_save_test")
            assert saved.access_token == "saved-initial-token"
            assert saved.expires_at is not None

    def test_raises_on_non_200(self, in_memory_secrets, clock):
        """Non-200 on initial token request raises OAuthInitialTokenError."""
        with responses.RequestsMock() as rs:
            rs.add(
                rs.POST,
                "https://api.otter.dev/v1/auth/token",
                status=400,
                body="bad request",
            )

            session = requests.Session()
            creds = MerchantCredentials(
                merchant_id="merchant_bad",
                public_api_url="https://api.otter.dev",
                client_id="bad-client",
                client_secret_encrypted="bad-secret",
            )
            in_memory_secrets.save(creds)

            refresher = OAuthRefresher(
                session=session, secrets=in_memory_secrets, clock=clock
            )

            with pytest.raises(OAuthInitialTokenError):
                refresher.request_initial_token("merchant_bad")
