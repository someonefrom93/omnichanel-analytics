"""SecretsPort Protocol and InMemorySecrets stub — PR1 plaintext implementation."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class MerchantCredentials(BaseModel):
    """Pydantic model for merchant credentials.

    PR1 uses plaintext storage.  # pragma: PR2 swap to KMS-backed impl
    """

    model_config = ConfigDict(frozen=True)

    merchant_id: str = Field(min_length=1, max_length=64)
    public_api_url: AnyHttpUrl
    client_id: str
    client_secret_encrypted: str  # plaintext stub for PR1
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: datetime | None = None  # UTC


class SecretsPort(Protocol):
    """Protocol for loading and saving merchant credentials."""

    def load(self, merchant_id: str) -> MerchantCredentials:
        """Load credentials for a merchant. Raises MerchantNotFoundError if not found."""
        ...

    def save(self, creds: MerchantCredentials) -> None:
        """Save credentials for a merchant."""
        ...


class MerchantNotFoundError(LookupError):
    """Raised when credentials for a merchant_id are not found."""


class InMemorySecrets:
    """PR1 stub for SecretsPort — holds credentials in a dict, no KMS."""

    def __init__(self, initial: dict[str, MerchantCredentials] | None = None) -> None:
        self._store: dict[str, MerchantCredentials] = initial or {}

    def load(self, merchant_id: str) -> MerchantCredentials:
        if merchant_id not in self._store:
            raise MerchantNotFoundError(
                f"No credentials found for merchant_id={merchant_id}"
            )
        return self._store[merchant_id]

    def save(self, creds: MerchantCredentials) -> None:
        self._store[creds.merchant_id] = creds
