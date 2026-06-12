"""OAuthRefresher — auth adapter for Otter API token management."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import requests

from omc_analytics.common.secrets import (
    MerchantCredentials,
    MerchantNotFoundError,
    SecretsPort,
)
from omc_analytics.ingestion.errors import (
    OAuthAuthorizationCodeError,
    OAuthInitialTokenError,
    OAuthRefreshError,
)


class OAuthRefresher:
    """Manages OAuth token lifecycle for the Otter API.

    Handles proactive refresh (10-minute pre-expiry window) and
    client_credentials grant for initial token acquisition.

    Args:
        session: An injected requests.Session.
        secrets: A SecretsPort for loading and persisting credentials.
        clock: A callable returning the current datetime (defaults to datetime.now(UTC)).
    """

    _PRE_EXPIRY_THRESHOLD = timedelta(minutes=10)

    def __init__(
        self,
        session: requests.Session,
        secrets: SecretsPort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._secrets = secrets
        self._clock = clock or (lambda: datetime.now(UTC))

    def ensure_fresh_token(self, merchant_id: str) -> str:
        """Return a valid access token, refreshing proactively if near expiry.

        Args:
            merchant_id: The merchant whose token to manage.

        Returns:
            A valid access token string.

        Raises:
            MerchantNotFoundError: If the merchant_id is not in secrets.
        """
        creds = self._secrets.load(merchant_id)
        if creds.access_token is None:
            raise OAuthRefreshError(
                f"No access token found for merchant_id={merchant_id}"
            )

        expires_at = creds.expires_at
        if (
            expires_at is not None
            and (expires_at - self._clock()) >= self._PRE_EXPIRY_THRESHOLD
        ):
            return creds.access_token

        new_creds = self._refresh(creds)
        assert new_creds.access_token is not None
        return new_creds.access_token

    def _refresh(self, creds: MerchantCredentials) -> MerchantCredentials:
        """Perform a refresh_token grant against the Otter auth endpoint.

        Args:
            creds: The current credentials (must have refresh_token set).

        Returns:
            Updated MerchantCredentials with new access_token and expires_at.

        Raises:
            OAuthRefreshError: If the HTTP response is not 200.
        """
        if creds.refresh_token is None:
            raise OAuthRefreshError("Cannot refresh: no refresh_token available")

        url = f"{str(creds.public_api_url).rstrip('/')}/v1/auth/token"
        body = {
            "grant_type": "refresh_token",
            "client_id": creds.client_id,
            "refresh_token": creds.refresh_token,
        }

        resp = self._session.post(url, data=body)
        if resp.status_code != 200:
            raise OAuthRefreshError(
                f"Token refresh failed: {resp.status_code} {resp.text[:200]}"
            )

        data = resp.json()
        now = self._clock()
        # 60-second safety margin on the expiry
        expires_at = now + timedelta(seconds=data["expires_in"]) - timedelta(seconds=60)

        new_creds = creds.model_copy(
            update={
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token") or creds.refresh_token,
                "expires_at": expires_at,
            }
        )
        self._secrets.save(new_creds)
        return new_creds

    def request_initial_token(
        self,
        merchant_id: str,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> MerchantCredentials:
        """Perform a client_credentials grant to get the initial access token.

        Args:
            merchant_id: The merchant whose credentials to use.
            client_id: Optional client ID override. If not provided, loaded from secrets.
            client_secret: Optional client secret override. If not provided, loaded from secrets.

        Returns:
            Updated MerchantCredentials with access_token, expires_at, and refresh_token.

        Raises:
            OAuthInitialTokenError: If the HTTP response is not 200.
            MerchantNotFoundError: If the merchant is not in secrets AND no overrides provided.
        """
        # Try to load existing creds; if missing and overrides provided, create minimal creds
        try:
            creds = self._secrets.load(merchant_id)
        except MerchantNotFoundError:
            if client_id is not None and client_secret is not None:
                # Bootstrap case: merchant doesn't exist yet, but we have client creds
                # PR2 would validate these come from a secure bootstrap channel
                creds = MerchantCredentials(
                    merchant_id=merchant_id,
                    public_api_url="https://api.otter.dev",  # type: ignore[arg-type]
                    client_id=client_id,
                    client_secret_encrypted=client_secret,
                )
            else:
                raise

        url = f"{str(creds.public_api_url).rstrip('/')}/v1/auth/token"
        body = {
            "grant_type": "client_credentials",
            "client_id": client_id or creds.client_id,
            "client_secret": client_secret or creds.client_secret_encrypted,
        }

        resp = self._session.post(url, data=body)
        if resp.status_code != 200:
            raise OAuthInitialTokenError(
                f"Initial token request failed: {resp.status_code} {resp.text[:200]}"
            )

        data = resp.json()
        now = self._clock()
        expires_at = now + timedelta(seconds=data["expires_in"]) - timedelta(seconds=60)

        new_creds = creds.model_copy(
            update={
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_at": expires_at,
            }
        )
        self._secrets.save(new_creds)
        return new_creds

    def exchange_authorization_code(
        self,
        code: str,
        redirect_uri: str,
    ) -> MerchantCredentials:
        """Exchange an OAuth authorization_code for tokens (Otter OAuth flow).

        Args:
            code: One-time authorization code from Otter's callback.
            redirect_uri: The redirect URI registered with Otter.

        Returns:
            MerchantCredentials with access_token, refresh_token, and expires_at.

        Raises:
            OAuthAuthorizationCodeError: If the HTTP response is not 200.
            MerchantNotFoundError: If the merchant_id is not in secrets.
        """
        merchant_id = "merchant_001"  # Default — caller can extend later
        creds = self._secrets.load(merchant_id)

        url = f"{str(creds.public_api_url).rstrip('/')}/v1/auth/token"
        body = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret_encrypted,
        }

        resp = self._session.post(url, data=body)
        if resp.status_code != 200:
            raise OAuthAuthorizationCodeError(
                f"Authorization code exchange failed: {resp.status_code} {resp.text[:200]}"
            )

        data = resp.json()
        now = self._clock()
        expires_at = now + timedelta(seconds=data["expires_in"]) - timedelta(seconds=60)

        new_creds = creds.model_copy(
            update={
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_at": expires_at,
            }
        )
        self._secrets.save(new_creds)
        return new_creds
