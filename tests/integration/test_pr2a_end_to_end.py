"""End-to-end integration tests for PR2a — KMSSecrets + PostgresLogs + config wiring.

These tests exercise the full stack with moto[s3,kms] + testcontainers Postgres.
They are opt-in via `pytest -m integration` — skipped by default.

Tests:
1. test_end_to_end_pipeline_uses_real_adapters
   — Full pipeline with KMSSecrets + PostgresLogs against moto + testcontainers
   — Asserts: secrets saved/loaded via KMSSecrets,1 SUCCESS log row, 3 S3 objects

2. test_kms_round_trip_produces_valid_envelope_encryption
   — Focused harness: save → inspect raw blob → load → verify plaintext recovered
   — Asserts:5 blob fields present, ciphertext != plaintext
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC
from pathlib import Path
from typing import Any

import boto3
import moto
import psycopg2
import pytest
import responses
from testcontainers.postgres import PostgresContainer

from omc_analytics.common.config import RunContext, logs_factory, secrets_factory
from omc_analytics.common.kms_secrets import InMemoryBlobStore
from omc_analytics.common.secrets import KMSSecrets, MerchantCredentials
from omc_analytics.ingestion.run import _build_deps, run_bronze_impl

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_fixture(name: str) -> dict:
    """Load a JSON fixture by name, stripping our provenance metadata."""
    path = Path(__file__).parent.parent / "fixtures" / "otter" / f"{name}.json"
    raw = json.loads(path.read_text())
    return {
        k: v
        for k, v in raw.items()
        if k not in ("provenance", "fixture_version", "endpoint")
    }


def _apply_ddl(connection: Any) -> None:
    """Apply the pipeline_execution_logs DDL to a fresh database."""
    ddl_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "omc_analytics"
        / "common"
        / "migrations"
        / "001_create_pipeline_execution_logs.sql"
    )
    ddl = ddl_path.read_text()
    with connection.cursor() as cur:
        cur.execute(ddl)
    connection.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kms_client():
    """moto KMS client."""
    with moto.mock_aws():
        client = boto3.client("kms", region_name="us-east-1")
        yield client


@pytest.fixture
def kms_key_id(kms_client) -> str:
    """Create a KMS key in moto and return its key_id."""
    with moto.mock_aws():
        response = kms_client.create_key(
            Description="PR2a test key",
            KeyUsage="ENCRYPT_DECRYPT",
            Origin="AWS_KMS",
        )
        key_id = response["KeyMetadata"]["KeyId"]
        # Need to use the key in the same moto context
        return key_id


# ---------------------------------------------------------------------------
# Integration tests — slow, opt-in
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_end_to_end_pipeline_uses_real_adapters(
    kms_client: Any,
    kms_key_id: str,
) -> None:
    """Full pipeline with KMSSecrets + PostgresLogs, moto S3/KMS, testcontainers Postgres.

    Asserts:
    - Secrets were saved AND loaded through KMSSecrets (envelope encryption roundtrip)
    - 1 row in pipeline_execution_logs with status=SUCCESS
    - 3 objects in S3 (orders, reports_enqueue, reports_result)
    - Merchant's S3 objects are at expected Hive-partitioned keys
    """
    # ---- Set up testcontainers Postgres ----
    try:
        pg_container = PostgresContainer("postgres:16-alpine")
        pg_container.start()
        pg_dsn = pg_container.get_connection_url(driver=None)
    except Exception as exc:
        pytest.skip(f"Docker not available or testcontainers failed: {exc}")

    try:
        # Apply DDL and build connection factory
        conn = psycopg2.connect(pg_dsn)
        _apply_ddl(conn)
        conn.close()

        def conn_factory(*args: Any, **kwargs: Any) -> Any:
            # psycopg2 calls the factory with a positional key argument; we ignore it.
            return psycopg2.connect(pg_dsn)

        # ---- Set up moto S3 ----
        with moto.mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="ofae-data-lakehouse-bronze-dev")

            # ---- Pre-seed credentials via KMSSecrets ----
            blob_store = InMemoryBlobStore()
            kmsSecrets = KMSSecrets(
                kms_client=kms_client,
                blob_store=blob_store,
                kms_key_id=kms_key_id,
            )

            merchant_id = "merchant_001"
            creds = MerchantCredentials(
                merchant_id=merchant_id,
                public_api_url="https://api.otter.dev",
                client_id="dev-client-id",
                client_secret_encrypted="dev-client-secret",
                access_token="dev-token-abc123",
                refresh_token="dev-refresh-xyz",
                expires_at=__import__("datetime").datetime(
                    2099, 12, 31, 23, 59, 59, tzinfo=UTC
                ),
            )
            kmsSecrets.save(creds)

            # Verify we can load it back (proves envelope encryption roundtrip)
            loaded = kmsSecrets.load(merchant_id)
            assert loaded.access_token == "dev-token-abc123"

            # ---- Build RunContext with real factories ----
            run_ctx = RunContext(
                run_id=uuid.uuid4(),
                merchant_id=merchant_id,
                env="dev",
                bucket_name="ofae-data-lakehouse-bronze-dev",
                run_timestamp_utc=__import__("datetime").datetime.now(UTC),
                secrets_backend="kms",
                logs_backend="postgres",
                kms_key_id=kms_key_id,
                pg_dsn=pg_dsn,
                aws_region="us-east-1",
            )

            # Wire real implementations via factories
            secrets = secrets_factory(
                run_ctx, kms_client=kms_client, blob_store=blob_store
            )
            logs = logs_factory(run_ctx, connection_factory=conn_factory)

            # ---- Load fixture responses ----
            orders_payload = load_fixture("orders_response")
            report_enqueue_payload = load_fixture("reports_enqueue_response")
            report_result_payload = load_fixture("reports_result_ready")

            # ---- Run the pipeline ----
            with responses.RequestsMock() as rs:
                rs.add(
                    responses.GET,
                    "https://api.otter.dev/v1/orders",
                    json=orders_payload,
                    status=200,
                )
                rs.add(
                    responses.POST,
                    "https://api.otter.dev/v1/reports",
                    json=report_enqueue_payload,
                    status=200,
                )
                rs.add(
                    responses.GET,
                    "https://api.otter.dev/v1/reports/job_abc123",
                    json=report_result_payload,
                    status=200,
                )

                _secrets, _logs, _oauth, _otter, _bronze, run_ctx = _build_deps(
                    merchant_id=merchant_id,
                    env="dev",
                    secrets=secrets,
                    logs=logs,
                    s3_client=s3_client,
                )

                run_bronze_impl(run_ctx)

            # ---- Assert S3 objects ----
            objects = s3_client.list_objects_v2(
                Bucket="ofae-data-lakehouse-bronze-dev"
            ).get("Contents", [])
            assert (
                len(objects) == 3
            ), f"Expected 3 S3 objects, got {len(objects)}: {[o['Key'] for o in objects]}"

            for obj in objects:
                key = obj["Key"]
                assert key.startswith(
                    f"otter/merchant_id={merchant_id}/"
                ), f"Key does not match partition scheme: {key}"
                assert (
                    "/year=" in key and "/month=" in key and "/day=" in key
                ), f"Key missing Hive partition: {key}"

            # ---- Assert PostgresLogs row ----
            verify_conn = psycopg2.connect(pg_dsn)
            with verify_conn.cursor() as cur:
                cur.execute(
                    "SELECT merchant_id, status FROM pipeline_execution_logs "
                    "WHERE merchant_id = %s",
                    (merchant_id,),
                )
                rows = cur.fetchall()
            verify_conn.close()

            assert len(rows) == 1, f"Expected 1 log row, got {len(rows)}"
            assert rows[0][1] == "SUCCESS", f"Expected SUCCESS, got {rows[0][1]}"

    finally:
        pg_container.stop()


@pytest.mark.integration
def test_kms_round_trip_produces_valid_envelope_encryption(
    kms_client: Any,
    kms_key_id: str,
) -> None:
    """Focused harness: save → inspect raw blob → load → verify plaintext recovered.

    This test proves the full envelope encryption cycle works with a real KMS key:
    1. Save a payload via KMSSecrets
    2. Inspect the raw blob to assert all 5 required fields are present
    3. Assert ciphertext is NOT the plaintext
    4. Load it back and verify the plaintext is byte-for-byte identical
    """
    blob_store = InMemoryBlobStore()
    kmsSecrets = KMSSecrets(
        kms_client=kms_client,
        blob_store=blob_store,
        kms_key_id=kms_key_id,
    )

    merchant_id = "merchant_test_001"
    creds = MerchantCredentials(
        merchant_id=merchant_id,
        public_api_url="https://api.otter.dev",
        client_id="test-client",
        client_secret_encrypted="test-secret",
        access_token="test-access-token-xyz",
        refresh_token="test-refresh-token-xyz",
        expires_at=__import__("datetime").datetime(
            2099, 12, 31, 23, 59, 59, tzinfo=UTC
        ),
    )

    # Step 1: Save
    kmsSecrets.save(creds)

    # Step 2: Inspect raw blob
    blob = blob_store.get(merchant_id)
    assert blob is not None, "Blob should be stored"

    required_fields = {
        "key_id",
        "ciphertext_blob",
        "encrypted_payload",
        "nonce",
        "aad_merchant_id",
    }
    assert required_fields.issubset(
        blob.keys()
    ), f"Blob missing required fields. Got: {blob.keys()}"

    # Step 3: Assert ciphertext is NOT plaintext
    plaintext_json = creds.model_dump_json().encode("utf-8")
    assert (
        blob["encrypted_payload"] != plaintext_json
    ), "ciphertext must not equal plaintext"

    # Step 4: Load back and verify
    loaded = kmsSecrets.load(merchant_id)
    assert loaded.merchant_id == creds.merchant_id
    assert loaded.access_token == creds.access_token
    assert loaded.refresh_token == creds.refresh_token
    assert loaded.public_api_url == creds.public_api_url
