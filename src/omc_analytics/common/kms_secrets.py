"""KMSSecrets — SecretsPort adapter using envelope encryption (KMS + AES-256-GCM).

# pragma: PR1 stub replaced by this real impl; InMemorySecrets remains the no-AWS dev path

Architecture:
    - kms_client is injected (boto3.client("kms")) — this class NEVER calls boto3 directly
    - blob_store is injected (BlobStore protocol) — this class NEVER talks to PostgreSQL directly
    - Both dependencies allow the same logic to be tested with an in-memory blob store
      and used in production with a Postgres-backed blob store.

Envelope encryption algorithm (save):
    1. kms_client.generate_data_key(KeyId=kms_key_id, KeySpec="AES_256")
       → {"Plaintext": bytes, "CiphertextBlob": bytes}
    2. AES-256-GCM encrypt JSON-serialized payload with os.urandom(12) nonce per call.
       Associated data (AAD) MUST include merchant_id to bind ciphertext to merchant.
    3. Store blob: {"key_id", "ciphertext_blob", "encrypted_payload", "nonce", "aad_merchant_id"}
    4. blob_store.put(merchant_id, blob_dict)
    5. Zeroize plaintext data key via bytearray overwrite.

Envelope decryption algorithm (load):
    1. blob = blob_store.get(merchant_id) → raise MerchantNotFoundError if None
    2. kms_client.decrypt(CiphertextBlob=blob["ciphertext_blob"])["Plaintext"]
    3. AES-256-GCM decrypt with same nonce + AAD
    4. Deserialize JSON
    5. Zeroize plaintext key
    6. Return deserialized dict
"""

from __future__ import annotations

import json
import os
from typing import Protocol

from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from omc_analytics.common.models import MerchantCredentials, MerchantNotFoundError

# ---------------------------------------------------------------------------
# BlobStore Protocol
# ---------------------------------------------------------------------------


class BlobStore(Protocol):
    """Protocol for persisting encrypted credential blobs."""

    def put(self, merchant_id: str, encrypted_blob: dict) -> None:
        """Store an encrypted blob for a merchant."""
        ...

    def get(self, merchant_id: str) -> dict | None:
        """Retrieve an encrypted blob for a merchant, or None if not found."""
        ...


# ---------------------------------------------------------------------------
# In-memory BlobStore (for unit tests)
# ---------------------------------------------------------------------------


class InMemoryBlobStore:
    """In-memory BlobStore implementation for unit tests.

    Stores raw bytes directly (no base64 encoding) to match how a real
    PostgreSQL BYTEA column would behave. Only for use in unit tests.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def put(self, merchant_id: str, encrypted_blob: dict) -> None:
        # Store a deep copy so tests can mutate the returned dict without
        # affecting the stored blob.
        self._store[merchant_id] = dict(encrypted_blob)

    def get(self, merchant_id: str) -> dict | None:
        # Return a copy so callers can mutate without affecting stored data.
        blob = self._store.get(merchant_id)
        return dict(blob) if blob is not None else None

    def get_all_blobs(self) -> dict[str, dict]:
        """Return a copy of the entire store (for testing)."""
        return {k: dict(v) for k, v in self._store.items()}


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class KMSKeyError(Exception):
    """Raised when KMS generate_data_key fails."""


class KMSDecryptError(Exception):
    """Raised when KMS decrypt fails."""


class MerchantBlobCorruptError(Exception):
    """Raised when the encrypted blob is corrupted, tampered, or decrypted with wrong key/AAD."""


# ---------------------------------------------------------------------------
# KMSSecrets adapter
# ---------------------------------------------------------------------------


class KMSSecrets:
    """SecretsPort adapter using AWS KMS envelope encryption.

    Args:
        kms_client: A boto3.client("kms") instance. The class never calls
            boto3.client() itself — this allows injection of a mocked client in tests.
        blob_store: A BlobStore implementation. In production this could be backed by
            PostgreSQL; in tests this is InMemoryBlobStore.
        kms_key_id: The KMS CMK KeyId or ARN to use for generate_data_key.
    """

    def __init__(  # type: ignore[no-untyped-def]
        self,
        kms_client,  # boto3 client — avoid runtime import
        blob_store: BlobStore,
        kms_key_id: str,
    ) -> None:
        self._kms_client = kms_client
        self._blob_store: BlobStore = blob_store
        self._kms_key_id = kms_key_id

    def save(self, creds: MerchantCredentials) -> None:
        """Encrypt and store credentials using envelope encryption."""
        # Step 1: Generate data key from KMS
        try:
            response = self._kms_client.generate_data_key(
                KeyId=self._kms_key_id,
                KeySpec="AES_256",
            )
        except ClientError as exc:
            raise KMSKeyError(f"generate_data_key failed: {exc}") from exc

        # Use bytearray for the plaintext key so we can zeroize it in-place.
        # AESGCM reads the key material at construction time (makes an internal copy),
        # after which we zeroize the source bytearray.
        plaintext_key_ba = bytearray(response["Plaintext"])
        ciphertext_blob: bytes = response["CiphertextBlob"]

        # Step 2: Serialize payload to JSON
        payload_bytes = creds.model_dump_json().encode("utf-8")

        # Step 3: Generate fresh 12-byte nonce per call
        nonce = os.urandom(12)

        # Step 4: AES-256-GCM encrypt
        # AAD binds the ciphertext to the merchant_id stored in the blob (defense in depth)
        aad = creds.merchant_id.encode("utf-8")
        aesgcm = AESGCM(plaintext_key_ba)
        ciphertext = aesgcm.encrypt(nonce, payload_bytes, aad)

        # Step 5: Build blob dict (raw bytes — works with InMemoryBlobStore and Postgres BYTEA)
        blob = {
            "key_id": self._kms_key_id,
            "ciphertext_blob": ciphertext_blob,
            "encrypted_payload": ciphertext,
            "nonce": nonce,
            "aad_merchant_id": creds.merchant_id,
        }

        # Step 6: Persist to blob store
        self._blob_store.put(creds.merchant_id, blob)

        # Step 7: Zeroize plaintext data key (in-place, before dropping reference)
        plaintext_key_ba[:] = b"\x00" * len(plaintext_key_ba)
        del plaintext_key_ba

    def load(self, merchant_id: str) -> MerchantCredentials:
        """Decrypt and return credentials. Raises MerchantNotFoundError if not found."""
        # Step 1: Retrieve blob
        blob = self._blob_store.get(merchant_id)
        if blob is None:
            raise MerchantNotFoundError(
                f"No credentials found for merchant_id={merchant_id}"
            )

        # Step 2: Validate required fields
        required_fields = {"key_id", "ciphertext_blob", "encrypted_payload", "nonce", "aad_merchant_id"}
        missing = required_fields - set(blob.keys())
        if missing:
            raise MerchantBlobCorruptError(
                f"Blob for {merchant_id!r} is missing required fields: {missing}"
            )

        try:
            # Step 3: Read stored fields (raw bytes from blob store)
            ciphertext_blob = blob["ciphertext_blob"]
            encrypted_payload = blob["encrypted_payload"]
            nonce = blob["nonce"]
            stored_merchant_id = blob["aad_merchant_id"]

            # Step 4: Decrypt the data key via KMS
            try:
                decrypt_response = self._kms_client.decrypt(
                    CiphertextBlob=ciphertext_blob,
                )
            except ClientError as exc:
                raise KMSDecryptError(f"decrypt failed: {exc}") from exc

            plaintext_key: bytes = decrypt_response["Plaintext"]

            # Step 5: AES-256-GCM decrypt
            # AAD binds decryption to the merchant_id stored in the blob.
            # If the blob's aad_merchant_id was tampered, AAD mismatch → decrypt fails.
            aad = stored_merchant_id.encode("utf-8")
            aesgcm = AESGCM(plaintext_key)
            try:
                payload_bytes = aesgcm.decrypt(nonce, encrypted_payload, aad)
            except Exception as exc:
                # cryptography.exceptions.InvalidTag inherits from Exception (not BaseException)
                # Catch broadly to include InvalidTag without importing cryptography here
                raise MerchantBlobCorruptError(
                    f"Decryption failed for {merchant_id!r}: {exc}"
                ) from exc

            # Step 6: Deserialize JSON
            try:
                creds_dict = json.loads(payload_bytes.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise MerchantBlobCorruptError(
                    f"Blob for {merchant_id!r} contains invalid JSON: {exc}"
                ) from exc

            # Step 7: Zeroize plaintext key
            key_bytearray = bytearray(plaintext_key)
            key_bytearray[:] = b"\x00" * len(key_bytearray)
            del key_bytearray

            # Step 8: Reconstruct MerchantCredentials
            return MerchantCredentials(**creds_dict)

        except MerchantBlobCorruptError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise MerchantBlobCorruptError(
                f"Blob for {merchant_id!r} is malformed: {exc}"
            ) from exc
