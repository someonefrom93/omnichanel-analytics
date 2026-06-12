"""Tests for OAuthRefresher.exchange_authorization_code (PR6a)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest import mock

import pytest
import requests
import responses

from omc_analytics.common.secrets import InMemorySecrets, MerchantCredentials
from omc_analytics.ingestion.errors import OAuthAuthorizationCodeError
from omc_analytics.ingestion.oauth import OAuthRefresher


@pytest.fixture
def secrets():
    """Pre-loaded secrets for exchange tests (minimal creds, no tokens yet)."""
    s = InMemorySecrets()
    creds = MerchantCredentials(
        merchant_id="merchant_001",
        public_api_url="https://api.otter.dev",
        client_id="dev-client-id",
        client_secret_encrypted="dev-client-secret",
    )
    s.save(creds)
    return s


@pytest.fixture
def clock():
    return mock.Mock(return_value=datetime.now(UTC))


class TestExchangeAuthorizationCode:
    """exchange_authorization_code tests per spec."""

    def test_happy_path_persists_creds(self, secrets, clock):
        """Happy path: POSTs form body, parses response, saves via SecretsPort."""
        session = requests.Session()
        refresher = OAuthRefresher(session=session, secrets=secrets, clock=clock)

        with responses.RequestsMock() as rs:
            rs.add(
                responses.POST,
                "https://api.otter.dev/v1/auth/token",
                json={
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                    "expires_in": 3600,
                    "scope": "read reports",
                    "token_type": "Bearer",
                },
                status=200,
            )

            creds = refresher.exchange_authorization_code(
                "auth-code-123", "https://myapp.com/callback"
            )

            assert creds.access_token == "new-access-token"
            assert creds.refresh_token == "new-refresh-token"
            assert creds.expires_at is not None

            # Verify persisted via SecretsPort
            saved = secrets.load("merchant_001")
            assert saved.access_token == "new-access-token"
            assert saved.refresh_token == "new-refresh-token"

            # Verify form body
            req = rs.calls[0].request
            assert "grant_type=authorization_code" in req.body
            assert "code=auth-code-123" in req.body
            assert "redirect_uri=https%3A%2F%2Fmyapp.com%2Fcallback" in req.body
            assert "client_id=dev-client-id" in req.body

    def test_missing_refresh_token_preserves_none(self, secrets, clock):
        """When Otter returns no refresh_token, creds.refresh_token stays None."""
        session = requests.Session()
        refresher = OAuthRefresher(session=session, secrets=secrets, clock=clock)

        with responses.RequestsMock() as rs:
            rs.add(
                responses.POST,
                "https://api.otter.dev/v1/auth/token",
                json={
                    "access_token": "at-no-refresh",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
                status=200,
            )

            creds = refresher.exchange_authorization_code(
                "code-456", "https://myapp.com/callback"
            )

            assert creds.access_token == "at-no-refresh"
            assert creds.refresh_token is None

    def test_non_200_raises_oauth_authorization_code_error(self, secrets, clock):
        """Non-200 response raises OAuthAuthorizationCodeError."""
        session = requests.Session()
        refresher = OAuthRefresher(session=session, secrets=secrets, clock=clock)

        with responses.RequestsMock() as rs:
            rs.add(
                responses.POST,
                "https://api.otter.dev/v1/auth/token",
                status=400,
                body="invalid_grant",
            )

            with pytest.raises(OAuthAuthorizationCodeError) as exc_info:
                refresher.exchange_authorization_code(
                    "bad-code", "https://myapp.com/callback"
                )
            assert "400" in str(exc_info.value)
