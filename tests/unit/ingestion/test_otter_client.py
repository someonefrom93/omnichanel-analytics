"""Tests for OtterClient HTTP adapter with 401 recovery and 429 backoff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import mock
from uuid import uuid4

import pytest
import requests
import responses

from omc_analytics.common.secrets import InMemorySecrets, MerchantCredentials
from omc_analytics.ingestion.backoff import RetryPolicy
from omc_analytics.ingestion.errors import (
    BackoffExhaustedError,
    OtterAPIError,
    ReportJobCancelledError,
    ReportJobFailedError,
)
from omc_analytics.ingestion.oauth import OAuthRefresher

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def merchant_creds():
    """Provide a MerchantCredentials instance."""
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
def in_memory_secrets(merchant_creds):
    """Provide InMemorySecrets pre-loaded with merchant_creds."""
    secrets = InMemorySecrets()
    secrets.save(merchant_creds)
    return secrets


@pytest.fixture
def rate_limit_policy():
    """RetryPolicy for 429 handling: 3 retries, base=1.0, cap=8.0."""
    return RetryPolicy(max_retries=3, base_seconds=1.0, cap_seconds=8.0, jitter=False)


@pytest.fixture
def transient_401_policy():
    """RetryPolicy for transient 401: 1 retry, base=0.5, cap=1.0."""
    return RetryPolicy(max_retries=1, base_seconds=0.5, cap_seconds=1.0, jitter=False)


@pytest.fixture
def run_id():
    """Provide a fixed UUID for log correlation."""
    return uuid4()


@pytest.fixture
def clock():
    """Provide a controllable clock."""
    return mock.Mock(return_value=datetime.now(UTC))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_otter_client(
    secrets,
    rate_limit_policy,
    transient_401_policy,
    run_id,
    clock,
    session,
):
    """Build an OtterClient with injected dependencies."""
    from omc_analytics.ingestion.otter_client import OtterClient

    oauth = OAuthRefresher(session=session, secrets=secrets, clock=clock)
    return OtterClient(
        session=session,
        secrets=secrets,
        oauth_refresher=oauth,
        clock=clock,
        rate_limit_policy=rate_limit_policy,
        transient_401_policy=transient_401_policy,
        run_id=run_id,
    )


# ---------------------------------------------------------------------------
# fetch_orders
# ---------------------------------------------------------------------------


class TestFetchOrders:
    """Test suite for fetch_orders."""

    def test_sends_bearer_and_x_store_id_headers(
        self, rate_limit_policy, transient_401_policy, run_id, clock, in_memory_secrets
    ):
        """fetch_orders must send Authorization and X-Store-Id headers."""
        session = requests.Session()
        client = make_otter_client(
            in_memory_secrets,
            rate_limit_policy,
            transient_401_policy,
            run_id,
            clock,
            session,
        )
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)

        with responses.RequestsMock() as rs:
            rs.add(
                rs.GET,
                "https://api.otter.dev/v1/orders",
                json={"orders": []},
                status=200,
            )
            client.fetch_orders("store_001", start, end)
            req = rs.calls[0].request
            assert "Authorization" in req.headers
            assert "Bearer valid-token" in req.headers["Authorization"]
            assert req.headers.get("X-Store-Id") == "store_001"

    def test_passes_start_and_end_query_params_iso8601(
        self, rate_limit_policy, transient_401_policy, run_id, clock, in_memory_secrets
    ):
        """fetch_orders passes start_date and end_date as ISO-8601 strings."""
        session = requests.Session()
        client = make_otter_client(
            in_memory_secrets,
            rate_limit_policy,
            transient_401_policy,
            run_id,
            clock,
            session,
        )
        start = datetime(2026, 1, 1, 12, 30, 0, tzinfo=UTC)
        end = datetime(2026, 1, 2, 12, 30, 0, tzinfo=UTC)

        with responses.RequestsMock() as rs:
            rs.add(
                rs.GET,
                "https://api.otter.dev/v1/orders",
                json={"orders": []},
                status=200,
            )
            client.fetch_orders("store_001", start, end)
            req = rs.calls[0].request
            assert "start_date=" in req.url
            assert "end_date=" in req.url
            assert "2026-01-01" in req.url
            assert "2026-01-02" in req.url

    def test_returns_parsed_json(
        self, rate_limit_policy, transient_401_policy, run_id, clock, in_memory_secrets
    ):
        """fetch_orders returns the parsed JSON response."""
        session = requests.Session()
        client = make_otter_client(
            in_memory_secrets,
            rate_limit_policy,
            transient_401_policy,
            run_id,
            clock,
            session,
        )
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)

        with responses.RequestsMock() as rs:
            rs.add(
                rs.GET,
                "https://api.otter.dev/v1/orders",
                json={"orders": [{"id": "order-1"}, {"id": "order-2"}]},
                status=200,
            )
            result = client.fetch_orders("store_001", start, end)
            assert result == {"orders": [{"id": "order-1"}, {"id": "order-2"}]}

    def test_two_stage_401_recovers_on_second_retry(
        self, rate_limit_policy, transient_401_policy, run_id, clock, in_memory_secrets
    ):
        """Sequence: 401 → 401 → 200. Assert: short backoff, OAuth refresh, then 200."""
        # Set token as near-expiry so refresh is triggered
        creds = in_memory_secrets.load("merchant_001")
        in_memory_secrets.save(
            creds.model_copy(
                update={"expires_at": datetime.now(UTC) + timedelta(minutes=1)}
            )
        )

        session = requests.Session()
        client = make_otter_client(
            in_memory_secrets,
            rate_limit_policy,
            transient_401_policy,
            run_id,
            clock,
            session,
        )
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)

        with responses.RequestsMock() as rs:
            rs.add(rs.GET, "https://api.otter.dev/v1/orders", status=401, body="")
            rs.add(rs.GET, "https://api.otter.dev/v1/orders", status=401, body="")
            rs.add(
                rs.POST,
                "https://api.otter.dev/v1/auth/token",
                json={
                    "access_token": "refreshed-token",
                    "expires_in": 3600,
                    "refresh_token": "new-refresh",
                    "token_type": "Bearer",
                },
                status=200,
            )
            rs.add(
                rs.GET,
                "https://api.otter.dev/v1/orders",
                json={"orders": []},
                status=200,
            )

            with mock.patch(
                "omc_analytics.ingestion.otter_client.time.sleep"
            ) as mock_sleep:
                result = client.fetch_orders("store_001", start, end)
                # 2 x 401 + 1 refresh + 1 success = 4 calls
                assert len(rs.calls) == 4
                assert mock_sleep.call_count == 1
                assert result == {"orders": []}

    def test_raises_after_three_401s(
        self, rate_limit_policy, transient_401_policy, run_id, clock, in_memory_secrets
    ):
        """Three consecutive 401s raise OtterAPIError."""
        creds = in_memory_secrets.load("merchant_001")
        in_memory_secrets.save(
            creds.model_copy(
                update={"expires_at": datetime.now(UTC) + timedelta(minutes=1)}
            )
        )

        session = requests.Session()
        client = make_otter_client(
            in_memory_secrets,
            rate_limit_policy,
            transient_401_policy,
            run_id,
            clock,
            session,
        )
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)

        with responses.RequestsMock() as rs:
            rs.add(rs.GET, "https://api.otter.dev/v1/orders", status=401, body="first")
            rs.add(rs.GET, "https://api.otter.dev/v1/orders", status=401, body="second")
            rs.add(rs.GET, "https://api.otter.dev/v1/orders", status=401, body="third")
            rs.add(
                rs.POST,
                "https://api.otter.dev/v1/auth/token",
                json={
                    "access_token": "refreshed-token",
                    "expires_in": 3600,
                    "refresh_token": "new-refresh",
                    "token_type": "Bearer",
                },
                status=200,
            )

            with pytest.raises(OtterAPIError) as exc_info:
                client.fetch_orders("store_001", start, end)
            assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# request_report
# ---------------------------------------------------------------------------


class TestRequestReport:
    """Test suite for request_report."""

    def test_request_report_returns_job_id(
        self, rate_limit_policy, transient_401_policy, run_id, clock, in_memory_secrets
    ):
        """request_report returns the jobId from the response."""
        session = requests.Session()
        client = make_otter_client(
            in_memory_secrets,
            rate_limit_policy,
            transient_401_policy,
            run_id,
            clock,
            session,
        )

        with responses.RequestsMock() as rs:
            rs.add(
                rs.POST,
                "https://api.otter.dev/v1/reports",
                json={"jobId": "job-abc123"},
                status=200,
            )
            result = client.request_report("store_001", {"report_type": "sales"})
            assert result == "job-abc123"


# ---------------------------------------------------------------------------
# poll_report
# ---------------------------------------------------------------------------


class TestPollReport:
    """Test suite for poll_report."""

    def test_poll_report_returns_payload_on_ready(
        self, rate_limit_policy, transient_401_policy, run_id, clock, in_memory_secrets
    ):
        """poll_report returns the full payload when status=READY."""
        session = requests.Session()
        client = make_otter_client(
            in_memory_secrets,
            rate_limit_policy,
            transient_401_policy,
            run_id,
            clock,
            session,
        )

        with responses.RequestsMock() as rs:
            rs.add(
                rs.GET,
                "https://api.otter.dev/v1/reports/job-abc123",
                json={"status": "READY", "payload": {"orders": [{"id": "order-1"}]}},
                status=200,
            )
            result = client.poll_report("store_001", "job-abc123")
            assert result["status"] == "READY"
            assert result["payload"] == {"orders": [{"id": "order-1"}]}

    def test_poll_report_raises_on_failed(
        self, rate_limit_policy, transient_401_policy, run_id, clock, in_memory_secrets
    ):
        """poll_report raises ReportJobFailedError when status=FAILED."""
        session = requests.Session()
        client = make_otter_client(
            in_memory_secrets,
            rate_limit_policy,
            transient_401_policy,
            run_id,
            clock,
            session,
        )

        with responses.RequestsMock() as rs:
            rs.add(
                rs.GET,
                "https://api.otter.dev/v1/reports/job-abc123",
                json={"status": "FAILED", "error": "something went wrong"},
                status=200,
            )
            with pytest.raises(ReportJobFailedError) as exc_info:
                client.poll_report("store_001", "job-abc123")
            assert exc_info.value.job_id == "job-abc123"

    def test_poll_report_raises_on_cancelled(
        self, rate_limit_policy, transient_401_policy, run_id, clock, in_memory_secrets
    ):
        """poll_report raises ReportJobCancelledError when status=CANCELLED."""
        session = requests.Session()
        client = make_otter_client(
            in_memory_secrets,
            rate_limit_policy,
            transient_401_policy,
            run_id,
            clock,
            session,
        )

        with responses.RequestsMock() as rs:
            rs.add(
                rs.GET,
                "https://api.otter.dev/v1/reports/job-abc123",
                json={"status": "CANCELLED"},
                status=200,
            )
            with pytest.raises(ReportJobCancelledError) as exc_info:
                client.poll_report("store_001", "job-abc123")
            assert exc_info.value.job_id == "job-abc123"


# ---------------------------------------------------------------------------
# 429 backoff
# ---------------------------------------------------------------------------


class Test429Backoff:
    """Test suite for 429 exponential backoff."""

    def test_429_triggers_exponential_backoff_with_jitter(
        self, rate_limit_policy, transient_401_policy, run_id, clock, in_memory_secrets
    ):
        """Sequence: 429 → 429 → 200. Assert wait calls with growing delays."""
        session = requests.Session()
        client = make_otter_client(
            in_memory_secrets,
            rate_limit_policy,
            transient_401_policy,
            run_id,
            clock,
            session,
        )
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)

        with responses.RequestsMock() as rs:
            rs.add(rs.GET, "https://api.otter.dev/v1/orders", status=429, body="")
            rs.add(rs.GET, "https://api.otter.dev/v1/orders", status=429, body="")
            rs.add(
                rs.GET,
                "https://api.otter.dev/v1/orders",
                json={"orders": []},
                status=200,
            )

            with mock.patch(
                "omc_analytics.ingestion.otter_client.time.sleep"
            ) as mock_sleep:
                result = client.fetch_orders("store_001", start, end)
                assert mock_sleep.call_count == 2
                delays = [call.args[0] for call in mock_sleep.call_args_list]
                assert delays[0] > 0
                assert delays[1] > delays[0]
                assert result == {"orders": []}

    def test_429_exhausts_after_3_retries_raises_backoff_exhausted(
        self, rate_limit_policy, transient_401_policy, run_id, clock, in_memory_secrets
    ):
        """Four consecutive 429s raise BackoffExhaustedError."""
        session = requests.Session()
        client = make_otter_client(
            in_memory_secrets,
            rate_limit_policy,
            transient_401_policy,
            run_id,
            clock,
            session,
        )
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)

        with responses.RequestsMock() as rs:
            for _ in range(4):
                rs.add(rs.GET, "https://api.otter.dev/v1/orders", status=429, body="")

            with pytest.raises(BackoffExhaustedError):
                client.fetch_orders("store_001", start, end)

    def test_429_during_401_recovery_uses_rate_limit_policy(
        self, rate_limit_policy, transient_401_policy, run_id, clock, in_memory_secrets
    ):
        """Sequence: 401, 429, 429, 200. Both policies are exercised."""
        creds = in_memory_secrets.load("merchant_001")
        in_memory_secrets.save(
            creds.model_copy(
                update={"expires_at": datetime.now(UTC) + timedelta(minutes=1)}
            )
        )

        session = requests.Session()
        client = make_otter_client(
            in_memory_secrets,
            rate_limit_policy,
            transient_401_policy,
            run_id,
            clock,
            session,
        )
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)

        with responses.RequestsMock() as rs:
            rs.add(rs.GET, "https://api.otter.dev/v1/orders", status=401, body="")
            rs.add(rs.GET, "https://api.otter.dev/v1/orders", status=429, body="")
            rs.add(rs.GET, "https://api.otter.dev/v1/orders", status=429, body="")
            rs.add(
                rs.GET,
                "https://api.otter.dev/v1/orders",
                json={"orders": []},
                status=200,
            )

            # Mock the OAuthRefresher._refresh to avoid mocking the POST inside retry
            with mock.patch.object(
                client._oauth,
                "_refresh",
                return_value=creds.model_copy(
                    update={"access_token": "refreshed-token"}
                ),
            ):
                with mock.patch(
                    "omc_analytics.ingestion.otter_client.time.sleep"
                ) as mock_sleep:
                    result = client.fetch_orders("store_001", start, end)
                    # 1st 401 backoff (0.5s) + 429 retry 1 (1.0s) + 429 retry 2 (2.0s) = 3 sleeps
                    assert mock_sleep.call_count == 3
                    assert result == {"orders": []}
