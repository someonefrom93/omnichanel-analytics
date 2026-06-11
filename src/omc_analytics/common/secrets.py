"""SecretsPort Protocol and InMemorySecrets stub — PR1 plaintext implementation."""

from __future__ import annotations

from typing import Protocol

# Re-export KMSSecrets and related types from the KMS-backed implementation.
# The public import surface is: from omc_analytics.common.secrets import KMSSecrets
# InMemorySecrets remains the no-AWS dev path.
from omc_analytics.common.kms_secrets import (  # noqa: F401
    BlobStore,
    InMemoryBlobStore,
    KMSDecryptError,
    KMSKeyError,
    KMSSecrets,
    MerchantBlobCorruptError,
)
from omc_analytics.common.models import MerchantCredentials, MerchantNotFoundError

__all__ = [
    "BlobStore",
    "InMemoryBlobStore",
    "InMemorySecrets",
    "KMSSecrets",
    "KMSDecryptError",
    "KMSKeyError",
    "MerchantBlobCorruptError",
    "MerchantCredentials",
    "MerchantNotFoundError",
    "SecretsPort",
]


class SecretsPort(Protocol):
    """Protocol for loading and saving merchant credentials."""

    def load(self, merchant_id: str) -> MerchantCredentials:
        """Load credentials for a merchant. Raises MerchantNotFoundError if not found."""
        ...

    def save(self, creds: MerchantCredentials) -> None:
        """Save credentials for a merchant."""
        ...


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
