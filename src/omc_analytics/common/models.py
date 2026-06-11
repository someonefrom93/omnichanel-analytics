"""Shared Pydantic models for the common package."""

from __future__ import annotations

from datetime import datetime

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


class MerchantNotFoundError(LookupError):
    """Raised when credentials for a merchant_id are not found."""
