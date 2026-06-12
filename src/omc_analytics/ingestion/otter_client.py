"""OtterClient — HTTP adapter for Otter Commerce API.

Implements two-stage 401 recovery (retry → refresh → retry) and
429 exponential backoff. All public methods delegate to
_request_with_401_recovery.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

import requests

from omc_analytics.common.secrets import SecretsPort
from omc_analytics.ingestion.backoff import RetryPolicy
from omc_analytics.ingestion.errors import (
    ReportJobCancelledError,
    ReportJobFailedError,
    Tier1AuthError,
    Tier2LatencyError,
)
from omc_analytics.ingestion.oauth import OAuthRefresher


class OtterClient:
    """HTTP client for the Otter Commerce API.

    Handles auth, 401 recovery, and 429 backoff transparently.

    Args:
        session: An injected requests.Session.
        secrets: A SecretsPort for loading merchant credentials.
        oauth_refresher: An OAuthRefresher instance for token refresh.
        clock: A callable returning the current datetime.
        rate_limit_policy: RetryPolicy for 429 handling (3 retries, base=1.0, cap=8.0).
        transient_401_policy: RetryPolicy for transient 401 (1 retry, base=0.5, cap=1.0).
        run_id: UUID for log correlation.
    """

    def __init__(
        self,
        session: requests.Session,
        secrets: SecretsPort,
        oauth_refresher: OAuthRefresher,
        clock: Callable[[], datetime],
        rate_limit_policy: RetryPolicy,
        transient_401_policy: RetryPolicy,
        run_id: UUID,
    ) -> None:
        self._session = session
        self._secrets = secrets
        self._oauth = oauth_refresher
        self._clock = clock
        self._rate_limit = rate_limit_policy
        self._transient_401 = transient_401_policy
        self._run_id = run_id

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def fetch_orders(
        self,
        store_id: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> dict[str, Any]:
        """Fetch orders for a store within a date range.

        Args:
            store_id: The store identifier.
            start_utc: Start of the date range (UTC).
            end_utc: End of the date range (UTC).

        Returns:
            The parsed JSON response from the orders endpoint.
        """
        creds = self._secrets.load("merchant_001")
        url = f"{str(creds.public_api_url).rstrip('/')}/v1/orders"
        params = {
            "start_date": start_utc.isoformat(),
            "end_date": end_utc.isoformat(),
        }
        headers = {
            "Authorization": f"Bearer {creds.access_token}",
            "X-Store-Id": store_id,
        }
        return self._request_with_401_recovery(
            "GET", url, params=params, headers=headers
        ).json()

    def request_report(self, store_id: str, body: dict[str, Any]) -> str:
        """Request a report job and return the jobId.

        Args:
            store_id: The store identifier.
            body: The report request body.

        Returns:
            The jobId string from the response.
        """
        creds = self._secrets.load("merchant_001")
        url = f"{str(creds.public_api_url).rstrip('/')}/v1/reports"
        headers = {
            "Authorization": f"Bearer {creds.access_token}",
            "X-Store-Id": store_id,
        }
        resp = self._request_with_401_recovery("POST", url, json=body, headers=headers)
        return resp.json()["jobId"]

    def poll_report(self, store_id: str, job_id: str) -> dict[str, Any]:
        """Poll a report job until READY/FAILED/CANCELLED.

        Args:
            store_id: The store identifier.
            job_id: The job identifier to poll.

        Returns:
            The full response dict. If status==READY, includes the payload.

        Raises:
            ReportJobFailedError: If the job status is FAILED.
            ReportJobCancelledError: If the job status is CANCELLED.
        """
        creds = self._secrets.load("merchant_001")
        url = f"{str(creds.public_api_url).rstrip('/')}/v1/reports/{job_id}"
        headers = {
            "Authorization": f"Bearer {creds.access_token}",
            "X-Store-Id": store_id,
        }
        resp = self._request_with_401_recovery("GET", url, headers=headers)
        data = resp.json()
        status = data.get("status")
        if status == "READY":
            return data
        if status == "FAILED":
            raise ReportJobFailedError(job_id)
        if status == "CANCELLED":
            raise ReportJobCancelledError(job_id)
        # Return sentinel for poller to re-attempt
        return {"status": status}

    # -------------------------------------------------------------------------
    # 401 Recovery
    # -------------------------------------------------------------------------

    def _request_with_401_recovery(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Execute a request with two-stage 401 recovery and 429 backoff.

        1. First attempt.
        2. On 401: short backoff + retry once (transient 401).
        3. On second 401: refresh token + retry once more.
        4. On third 401: raise OtterAPIError.

        429 handling wraps the above: if a 429 is received at any point,
        apply the rate_limit_policy (up to 3 retries) before re-attempting.
        """
        attempt = 0
        # Strategy: initial call + transient-401 retry + refresh + refresh-retry = 3 calls max after initial

        while True:
            resp = self._session.request(method, url, **kwargs)
            attempt += 1

            if resp.status_code == 401:
                if attempt == 1:
                    # First 401: short backoff then retry
                    wait_time = self._transient_401.wait_for(1)
                    time.sleep(wait_time)
                    continue
                elif attempt == 2:
                    # Second 401: refresh token then retry
                    try:
                        self._oauth.ensure_fresh_token("merchant_001")
                    except Exception:
                        pass  # If refresh fails, still try with refreshed creds
                    # Update the Authorization header with potentially new token
                    creds = self._secrets.load("merchant_001")
                    if "headers" in kwargs:
                        kwargs["headers"][
                            "Authorization"
                        ] = f"Bearer {creds.access_token}"
                    continue
                else:
                    # Third 401: give up → Tier 1 auth error
                    raise Tier1AuthError(
                        f"Auth failure after 3 consecutive 401s: {resp.status_code} {resp.text[:200]}"
                    )

            if resp.status_code == 429:
                # Apply rate-limit backoff
                retry_count = attempt - 1
                if not self._rate_limit.should_retry(retry_count):
                    raise Tier2LatencyError(
                        f"Rate limit backoff exhausted after {attempt} attempts: 429"
                    )
                wait_time = self._rate_limit.wait_for(retry_count)
                time.sleep(wait_time)
                continue

            if 500 <= resp.status_code < 600:
                # Server error — raise as Tier 2 latency error (no retry)
                raise Tier2LatencyError(
                    f"Server error {resp.status_code}: {resp.text[:200]}"
                )

            # Success (2xx)
            return resp
