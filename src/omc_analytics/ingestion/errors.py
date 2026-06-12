"""Custom errors for the ingestion layer."""

from __future__ import annotations


class BronzeWriteError(Exception):
    """Raised when a boto3 put_object call fails."""


class OAuthRefreshError(Exception):
    """Raised when a token refresh request fails."""


class OAuthInitialTokenError(Exception):
    """Raised when an initial (client_credentials) token request fails."""


class OtterAPIError(Exception):
    """Raised when the Otter API returns an unexpected non-OK status after all retries."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"OtterAPIError({status_code}): {body[:200]}")


class BackoffExhaustedError(Exception):
    """Raised after all 429 retries are exhausted."""


class ReportJobFailedError(Exception):
    """Raised when a report job poll returns status=FAILED."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"Report job {job_id!r} failed")


class ReportJobCancelledError(Exception):
    """Raised when a report job poll returns status=CANCELLED."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"Report job {job_id!r} was cancelled")


class ReportPollingExhaustedError(Exception):
    """Raised when report polling exhausts all retries without reaching READY."""

    def __init__(self, job_id: str, max_retries: int) -> None:
        self.job_id = job_id
        self.max_retries = max_retries
        super().__init__(
            f"Report job {job_id!r} polling exhausted after {max_retries} retries without reaching READY"
        )


# ---------------------------------------------------------------------------
# PR6a: Typed error tiers for Streamlit UI classification
# ---------------------------------------------------------------------------


class Tier1AuthError(Exception):
    """Authentication/authorization failure (401/403).

    Raised by the ingestion layer when Otter responds with persistent
    401 or 403 errors. Tier 1 errors surface a warning banner in the UI.
    """


class Tier2LatencyError(Exception):
    """Infrastructure/latency failure (429 exhaustion, 5xx).

    Raised when Otter API rate limits are exhausted or server errors
    persist. Tier 2 errors surface an info banner in the UI.
    """


class OAuthAuthorizationCodeError(Exception):
    """Raised when the authorization_code exchange fails (non-200)."""
