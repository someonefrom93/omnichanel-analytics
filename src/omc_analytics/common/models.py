"""Shared Pydantic models for the common package."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator


class MerchantCredentials(BaseModel):
    """Pydantic model for merchant credentials.

    PR1 uses plaintext storage.  # pragma: PR2 swap to KMS-backed impl
    PR4a adds pii_salt for salted PII hashing.
    """

    model_config = ConfigDict(frozen=True)

    merchant_id: str = Field(min_length=1, max_length=64)
    public_api_url: AnyHttpUrl
    client_id: str
    client_secret_encrypted: str  # plaintext stub for PR1
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: datetime | None = None  # UTC
    pii_salt: str | None = Field(default=None, validate_default=True)

    @field_validator("pii_salt", mode="before")
    @classmethod
    def _generate_salt_if_missing(cls, v: str | None) -> str:
        """Auto-generate a UUID4 hex salt if none was provided."""
        if v is None:
            return uuid4().hex  # 32 chars, no hyphens
        if not isinstance(v, str):
            raise ValueError("pii_salt must be a string")
        if len(v) != 32:
            raise ValueError(f"pii_salt must be 32 hex chars, got {len(v)}")
        return v


class MerchantNotFoundError(LookupError):
    """Raised when credentials for a merchant_id are not found."""
