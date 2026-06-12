"""Tests for typed error classification in OtterClient (PR6a)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import mock
from uuid import uuid4

import pytest
import requests
import responses

from omc_analytics.common.secrets import InMemorySecrets, MerchantCredentials
from omc_analytics.ingestion.backoff import RetryPolicy
from omc_analytics.ingestion.errors import Tier1AuthError, Tier2LatencyError
from omc_analytics.ingestion.oauth import OAuthRefresher
from omc_analytics.ingestion.otter_client import OtterClient


@pytest.fixture
def merchant_creds():
    return MerchantCredentials(
        merchant_id="merchant_001",
        public_api_url="https://api.otter.dev",
        client_id="dev-client-id",
        client_secret_encrypted="dev-client-secret",
        access_token="valid-token",
        refresh_token="refresh-token",
        expires_at=datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC),
    )


@pytest.fixture
def secrets(merchant_creds):
    s = InMemorySecrets()
    s.save(merchant_creds)
    return s


@pytest.fixture
def client(secrets):
    session = requests.Session()
    clock = mock.Mock(return_value=datetime.now(UTC))
    oauth = OAuthRefresher(session=session, secrets=secrets, clock=clock)
    return OtterClient(
        session=session,
        secrets=secrets,
        oauth_refresher=oauth,
        clock=clock,
        rate_limit_policy=RetryPolicy(max_retries=3, base_seconds=0.01, cap_seconds=0.1, jitter=False),
        transient_401_policy=RetryPolicy(max_retries=1, base_seconds=0.01, cap_seconds=0.1, jitter=False),
        run_id=uuid4(),
    )


class TestTier1AuthErrorOn401:
    """Three consecutive 401s MUST raise Tier1AuthError."""

    def test_three_consecutive_401s_raise_tier1(self, client, secrets):
        creds = secrets.load("merchant_001")
        secrets.save(creds.model_copy(update={"expires_at": datetime.now(UTC) + timedelta(minutes=1)}))

        with responses.RequestsMock() as rs:
            rs.add(responses.GET, "https://api.otter.dev/v1/orders", status=401, body="first")
            rs.add(responses.GET, "https://api.otter.dev/v1/orders", status=401, body="second")
            rs.add(responses.GET, "https://api.otter.dev/v1/orders", status=401, body="third")
            rs.add(responses.POST, "https://api.otter.dev/v1/auth/token",
                    json={"access_token": "t", "expires_in": 3600, "token_type": "Bearer"}, status=200)

            start = datetime(2026, 1, 1, tzinfo=UTC)
            end = datetime(2026, 1, 2, tzinfo=UTC)

            with mock.patch("omc_analytics.ingestion.otter_client.time.sleep"):
                with pytest.raises(Tier1AuthError) as exc_info:
                    client.fetch_orders("store_001", start, end)
                assert "401" in str(exc_info.value)


class TestTier2LatencyErrorOnBackoffExhaustion:
    """429 backoff exhaustion MUST raise Tier2LatencyError."""

    def test_429_exhaustion_raises_tier2(self, client):
        with responses.RequestsMock() as rs:
            for _ in range(4):
                rs.add(responses.GET, "https://api.otter.dev/v1/orders", status=429, body="")

            start = datetime(2026, 1, 1, tzinfo=UTC)
            end = datetime(2026, 1, 2, tzinfo=UTC)

            with mock.patch("omc_analytics.ingestion.otter_client.time.sleep"):
                with pytest.raises(Tier2LatencyError) as exc_info:
                    client.fetch_orders("store_001", start, end)
                assert "429" in str(exc_info.value)


class TestTier2LatencyErrorOn5xx:
    """5xx server errors MUST raise Tier2LatencyError immediately."""

    def test_502_raises_tier2(self, client):
        with responses.RequestsMock() as rs:
            rs.add(responses.GET, "https://api.otter.dev/v1/orders", status=502, body="Bad Gateway")

            start = datetime(2026, 1, 1, tzinfo=UTC)
            end = datetime(2026, 1, 2, tzinfo=UTC)

            with mock.patch("omc_analytics.ingestion.otter_client.time.sleep"):
                with pytest.raises(Tier2LatencyError) as exc_info:
                    client.fetch_orders("store_001", start, end)
                assert "502" in str(exc_info.value)

    def test_503_raises_tier2(self, client):
        with responses.RequestsMock() as rs:
            rs.add(responses.GET, "https://api.otter.dev/v1/orders", status=503, body="Service Unavailable")

            start = datetime(2026, 1, 1, tzinfo=UTC)
            end = datetime(2026, 1, 2, tzinfo=UTC)

            with mock.patch("omc_analytics.ingestion.otter_client.time.sleep"):
                with pytest.raises(Tier2LatencyError) as exc_info:
                    client.fetch_orders("store_001", start, end)
                assert "503" in str(exc_info.value)
