"""Tests for MerchantCredentials pii_salt field (PR4a).

Validates auto-generation, immutability, round-trip, and length validation.
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from omc_analytics.common.models import MerchantCredentials


class TestMerchantCredentialsPiiSalt:
    """PR4a: pii_salt field on MerchantCredentials."""

    def test_pii_salt_auto_generated_when_absent(self) -> None:
        """Salt auto-generated as 32-char hex when not provided."""
        creds = MerchantCredentials(
            merchant_id="M1",
            public_api_url="https://api.otter.dev",
            client_id="cid",
            client_secret_encrypted="secret",
        )
        assert creds.pii_salt is not None
        assert len(creds.pii_salt) == 32
        # Must be all lowercase hex (UUID4.hex output)
        assert re.fullmatch(r"[0-9a-f]{32}", creds.pii_salt)

    def test_pii_salt_auto_generated_when_none_explicit(self) -> None:
        """Salt auto-generated when explicitly set to None."""
        creds = MerchantCredentials(
            merchant_id="M1",
            public_api_url="https://api.otter.dev",
            client_id="cid",
            client_secret_encrypted="secret",
            pii_salt=None,
        )
        assert creds.pii_salt is not None
        assert len(creds.pii_salt) == 32

    def test_pii_salt_preserved_when_provided(self) -> None:
        """Explicit salt is preserved as-is."""
        creds = MerchantCredentials(
            merchant_id="M1",
            public_api_url="https://api.otter.dev",
            client_id="cid",
            client_secret_encrypted="secret",
            pii_salt="a" * 32,
        )
        assert creds.pii_salt == "a" * 32

    def test_pii_salt_unique_per_instance(self) -> None:
        """Two instances without salt get different auto-generated salts."""
        creds1 = MerchantCredentials(
            merchant_id="M1",
            public_api_url="https://api.otter.dev",
            client_id="cid",
            client_secret_encrypted="secret",
        )
        creds2 = MerchantCredentials(
            merchant_id="M2",
            public_api_url="https://api.otter.dev",
            client_id="cid",
            client_secret_encrypted="secret",
        )
        assert creds1.pii_salt != creds2.pii_salt

    def test_pii_salt_rejects_wrong_length(self) -> None:
        """Explicitly provided salt of wrong length is rejected."""
        with pytest.raises(ValidationError):
            MerchantCredentials(
                merchant_id="M1",
                public_api_url="https://api.otter.dev",
                client_id="cid",
                client_secret_encrypted="secret",
                pii_salt="too-short",
            )

    def test_pii_salt_field_is_optional_in_init(self) -> None:
        """pii_salt is not a required constructor argument."""
        creds = MerchantCredentials(
            merchant_id="M1",
            public_api_url="https://api.otter.dev",
            client_id="cid",
            client_secret_encrypted="secret",
        )
        # After construction, pii_salt must be a str (not None)
        assert isinstance(creds.pii_salt, str)
        assert len(creds.pii_salt) == 32
