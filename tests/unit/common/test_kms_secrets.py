"""Tests for KMSSecrets — unit tests with moto[kms] mock."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest import mock

import boto3
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from moto import mock_aws

from omc_analytics.common.secrets import (
    BlobStore,
    InMemoryBlobStore,
    KMSDecryptError,
    KMSKeyError,
    KMSSecrets,
    MerchantBlobCorruptError,
    MerchantCredentials,
    MerchantNotFoundError,
)

# ---------------------------------------------------------------------------
# Fixture: KMS key (autouse, mocked)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def kms_key():
    """Create a moto-mocked KMS key for each test."""
    mock = mock_aws()
    mock.start()
    client = boto3.client("kms", region_name="us-east-1")
    response = client.create_key(Description="test")
    key_id = response["KeyMetadata"]["KeyId"]
    yield key_id
    mock.stop()


# ---------------------------------------------------------------------------
# Helper: build a KMSSecrets + InMemoryBlobStore instance
# ---------------------------------------------------------------------------


def _make_kms_secrets(kms_key_id: str):
    """Return (KMSSecrets, InMemoryBlobStore) wired together."""
    kms_client = boto3.client("kms", region_name="us-east-1")
    blob_store = InMemoryBlobStore()
    return KMSSecrets(
        kms_client=kms_client, blob_store=blob_store, kms_key_id=kms_key_id
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_save_then_load_roundtrips_payload(kms_key):
    """Happy path: save a dict, load returns the same dict."""
    secrets = _make_kms_secrets(kms_key)
    creds = MerchantCredentials(
        merchant_id="M1",
        public_api_url="https://api.example.com",
        client_id="cid",
        client_secret_encrypted="secret",
        access_token="token",
        refresh_token="refresh",
        expires_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    secrets.save(creds)
    loaded = secrets.load("M1")
    assert loaded.merchant_id == creds.merchant_id
    assert loaded.public_api_url == creds.public_api_url
    assert loaded.client_id == creds.client_id
    assert loaded.client_secret_encrypted == creds.client_secret_encrypted
    assert loaded.access_token == creds.access_token
    assert loaded.refresh_token == creds.refresh_token
    assert loaded.expires_at == creds.expires_at


def test_save_generates_fresh_nonce_per_call(kms_key):
    """Call save 1000 times, assert all 1000 stored nonces are unique."""
    secrets = _make_kms_secrets(kms_key)
    nonces: set[bytes] = set()
    for i in range(1000):
        m = f"M{i}"
        creds = MerchantCredentials(
            merchant_id=m,
            public_api_url="https://api.example.com",
            client_id="cid",
            client_secret_encrypted=f"secret{i}",
        )
        secrets.save(creds)
        blob = secrets._blob_store.get(m)
        nonces.add(blob["nonce"])
    assert len(nonces) == 1000, f"Expected 1000 unique nonces, got {len(nonces)}"


def test_save_serializes_payload_as_json(kms_key):
    """Assert the decrypted payload parses as JSON with the original keys."""
    secrets = _make_kms_secrets(kms_key)
    kms_client = boto3.client("kms", region_name="us-east-1")  # use mocked client
    creds = MerchantCredentials(
        merchant_id="M1",
        public_api_url="https://api.example.com",
        client_id="my-client",
        client_secret_encrypted="my-secret",
        access_token="atoken",
        refresh_token="rtoken",
    )
    secrets.save(creds)
    blob = secrets._blob_store.get("M1")
    # blob stores raw bytes (not base64) to match Postgres BYTEA behavior
    plaintext_key = kms_client.decrypt(CiphertextBlob=blob["ciphertext_blob"])[
        "Plaintext"
    ]
    nonce = blob["nonce"]
    aad = b"M1"
    ciphertext = blob["encrypted_payload"]
    aesgcm = AESGCM(plaintext_key)
    decrypted = aesgcm.decrypt(nonce, ciphertext, aad)
    parsed = json.loads(decrypted)
    assert parsed["merchant_id"] == "M1"
    assert parsed["client_id"] == "my-client"
    # cleanup
    bytearray_key = bytearray(plaintext_key)
    bytearray_key[:] = b"\x00" * len(bytearray_key)


def test_save_stores_all_five_required_blob_fields(kms_key):
    """Blob dict has exactly the 5 required fields including aad_merchant_id."""
    secrets = _make_kms_secrets(kms_key)
    creds = MerchantCredentials(
        merchant_id="M1",
        public_api_url="https://api.example.com",
        client_id="cid",
        client_secret_encrypted="secret",
    )
    secrets.save(creds)
    blob = secrets._blob_store.get("M1")
    required = {
        "key_id",
        "ciphertext_blob",
        "encrypted_payload",
        "nonce",
        "aad_merchant_id",
    }
    assert set(blob.keys()) == required, f"Expected {required}, got {set(blob.keys())}"


def test_load_raises_merchant_not_found_for_unknown_merchant(kms_key):
    """Load on empty blob store raises MerchantNotFoundError."""
    secrets = _make_kms_secrets(kms_key)
    with pytest.raises(MerchantNotFoundError):
        secrets.load("UNKNOWN")


def test_load_raises_blob_corrupt_on_tampered_payload(kms_key):
    """Save, then flip a bit in encrypted_payload, expect MerchantBlobCorruptError."""
    secrets = _make_kms_secrets(kms_key)
    creds = MerchantCredentials(
        merchant_id="M1",
        public_api_url="https://api.example.com",
        client_id="cid",
        client_secret_encrypted="secret",
    )
    secrets.save(creds)
    blob = secrets._blob_store.get("M1")
    # Tamper: flip LSB of first byte of encrypted_payload (raw bytes)
    encrypted_payload = blob["encrypted_payload"]
    tampered = bytes([encrypted_payload[0] ^ 0x01]) + encrypted_payload[1:]
    blob["encrypted_payload"] = tampered
    secrets._blob_store.put("M1", blob)
    with pytest.raises(MerchantBlobCorruptError):
        secrets.load("M1")


def test_load_raises_blob_corrupt_on_wrong_merchant_id_aad(kms_key):
    """Save for merchant A, corrupt blob's aad_merchant_id to B, load A → AAD mismatch."""
    secrets = _make_kms_secrets(kms_key)
    creds_a = MerchantCredentials(
        merchant_id="MerchantA",
        public_api_url="https://api.example.com",
        client_id="cid",
        client_secret_encrypted="secret",
    )
    secrets.save(creds_a)
    # Corrupt the blob's aad_merchant_id field (stored AAD in the blob)
    blob = secrets._blob_store.get("MerchantA")
    blob["aad_merchant_id"] = "MerchantB"  # type: ignore[assignment]
    secrets._blob_store.put("MerchantA", blob)
    # load("MerchantA") → retrieves blob → AAD = "MerchantB" (corrupted) → mismatch
    with pytest.raises(MerchantBlobCorruptError):
        secrets.load("MerchantA")


def test_save_zeroizes_plaintext_data_key(kms_key):
    """After save returns, the plaintext key bytearray used for encryption
    must be all zeros in place. AESGCM copies the key at construction time,
    so zeroization must happen AFTER the AESGCM(...) call and BEFORE the
    bytearray reference is dropped.

    The spy captures the SAME bytearray object (by identity) that the impl
    passed to AESGCM. After save() returns, that same bytearray should be
    zeroized in place.
    """
    secrets = _make_kms_secrets(kms_key)
    creds = MerchantCredentials(
        merchant_id="M1",
        public_api_url="https://api.example.com",
        client_id="cid",
        client_secret_encrypted="secret",
    )

    # Hold a strong reference to the bytearray the impl passes to AESGCM.
    # We capture by identity (not by copy) so that if the impl zeroizes the
    # bytearray in place, our reference sees the zeros.
    captured_bytearray_ref: list[bytearray] = []

    original_aesgcm_init = AESGCM.__init__

    def spy_aesgcm_init(self, key):
        # Only capture if the impl actually passed a bytearray (our impl does).
        if isinstance(key, bytearray):
            # Append the SAME object reference. Do NOT copy.
            captured_bytearray_ref.append(key)
        original_aesgcm_init(self, key)

    with mock.patch.object(AESGCM, "__init__", spy_aesgcm_init):
        secrets.save(creds)

    assert (
        len(captured_bytearray_ref) == 1
    ), "AESGCM should have been instantiated once with a bytearray key"
    # The impl must zeroize the bytearray in place after the AESGCM construction.
    # Since we hold a strong reference to the same object, we observe the zeros.
    plaintext_key_ref = captured_bytearray_ref[0]
    assert bytes(plaintext_key_ref) == b"\x00" * 32, (
        f"Expected plaintext key bytearray to be zeroized in place, "
        f"got {bytes(plaintext_key_ref)!r}"
    )


def test_save_wraps_boto3_client_error_on_generate(kms_key):
    """Mock generate_data_key to raise ClientError, expect KMSKeyError."""
    secrets = _make_kms_secrets(kms_key)
    from botocore.exceptions import ClientError

    creds = MerchantCredentials(
        merchant_id="M1",
        public_api_url="https://api.example.com",
        client_id="cid",
        client_secret_encrypted="secret",
    )
    error_response = {
        "Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}
    }
    client_error = ClientError(error_response, "GenerateDataKey")

    # Patch the generate_data_key method on the actual kms_client stored in KMSSecrets
    with mock.patch.object(
        secrets._kms_client, "generate_data_key", side_effect=client_error
    ):
        with pytest.raises(KMSKeyError):
            secrets.save(creds)


def test_load_wraps_boto3_client_error_on_decrypt(kms_key):
    """Save successfully, then mock decrypt to raise ClientError, expect KMSDecryptError."""
    secrets = _make_kms_secrets(kms_key)
    from botocore.exceptions import ClientError

    creds = MerchantCredentials(
        merchant_id="M1",
        public_api_url="https://api.example.com",
        client_id="cid",
        client_secret_encrypted="secret",
    )
    secrets.save(creds)

    error_response = {
        "Error": {"Code": "InvalidCiphertextException", "Message": "Invalid cipher"}
    }
    client_error = ClientError(error_response, "Decrypt")

    # Patch the decrypt method on the actual kms_client stored in KMSSecrets
    with mock.patch.object(secrets._kms_client, "decrypt", side_effect=client_error):
        with pytest.raises(KMSDecryptError):
            secrets.load("M1")


def test_blob_store_protocol_compatible_with_in_memory(kms_key):
    """Smoke test: InMemoryBlobStore implements the BlobStore protocol."""
    store: BlobStore = InMemoryBlobStore()
    assert hasattr(store, "put")
    assert hasattr(store, "get")
    # put and get work without raising
    blob_dict = {
        "key_id": "k1",
        "ciphertext_blob": b"ct",
        "encrypted_payload": b"ep",
        "nonce": b"n",
        "aad_merchant_id": "M1",
    }
    store.put("M1", blob_dict)
    result = store.get("M1")
    assert result == blob_dict
    assert store.get("UNKNOWN") is None
