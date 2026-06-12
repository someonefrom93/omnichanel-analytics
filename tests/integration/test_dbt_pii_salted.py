"""Integration test for PR4a salted PII hashing on silver_orders.

Runs dbt build with OMCAE_PII_SALT set, then asserts:
- The 2 new salted columns exist in the materialized table.
- Salted columns are not null on every row.
- Salted hashes are deterministic across runs.
- Raw hash columns are preserved.

Mirrors test_dbt_silver_orders_e2e.py pattern: moto S3 + dbtRunner.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import boto3
import duckdb
import pytest
from moto import mock_aws

REPO_ROOT = Path(__file__).parent.parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "otter" / "orders_response.json"
DBT_PROJECT = REPO_ROOT / "dbt_project"

BRONZE_KEY = (
    "otter/merchant_id=merchant_001/"
    "year=2026/month=06/day=10/"
    "orders-20260610T120000Z.json"
)
BRONZE_BUCKET = "ofae-data-lakehouse-bronze-dev"


def _dbt_via_dbtRunner(
    project_dir: Path,
    profiles_dir: Path,
    select: str = "silver_orders",
    extra_env: dict | None = None,
) -> tuple[bool, str]:
    """Run dbt build via dbtRunner in-process."""
    from dbt.cli.main import dbtRunner

    env = {
        "OMCAE_BRONZE_PATH": f"s3://{BRONZE_BUCKET}",
    }
    if extra_env:
        env.update(extra_env)
    for k, v in env.items():
        os.environ[k] = v

    try:
        runner = dbtRunner()
        args = [
            "build",
            "--select",
            select,
            "--project-dir",
            str(project_dir),
            "--profiles-dir",
            str(profiles_dir),
            "--quiet",
        ]
        result = runner.invoke(args)
        exception_msg = ""
        if result.exception:
            exception_msg = str(result.exception)
        return result.success, exception_msg
    finally:
        for k in env:
            os.environ.pop(k, None)


def _fetch_fixture_from_moto(
    s3_client,
    bucket: str,
    key: str,
    tmp_dir: Path,
) -> Path:
    """Fetch a JSON object from moto S3 into a local temp file."""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    body_bytes = response["Body"].read()
    local_path = tmp_dir / key.replace("/", "_")
    local_path.write_bytes(body_bytes)
    return local_path


def _setup_dbt_env(tmp_path: Path, s3_client) -> tuple[Path, Path, str]:
    """Set up temp DuckDB, profiles, and seed bronze.orders.

    Returns (duckdb_path, profiles_dir, extra_env dict-compatible kwargs).
    """
    s3_client.create_bucket(Bucket=BRONZE_BUCKET)

    fixture_raw = json.loads(FIXTURE.read_text())
    fixture_body = json.dumps(
        {
            k: v
            for k, v in fixture_raw.items()
            if k not in ("source", "version", "endpoint")
        }
    )
    s3_client.put_object(Bucket=BRONZE_BUCKET, Key=BRONZE_KEY, Body=fixture_body)

    duckdb_path = tmp_path / "pii_salted.duckdb"
    profiles_dir = tmp_path / "dbt_profiles"
    profiles_dir.mkdir()

    profile_content = f"""
ofae_analytics:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: '{duckdb_path}'
      threads: 1
"""
    (profiles_dir / "profiles.yml").write_text(profile_content)

    moto_fetch_dir = tmp_path / "moto_fetch"
    moto_fetch_dir.mkdir()

    con = duckdb.connect(str(duckdb_path))
    con.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    local_fixture_path = _fetch_fixture_from_moto(
        s3_client, BRONZE_BUCKET, BRONZE_KEY, moto_fetch_dir
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE bronze.orders AS
        SELECT * FROM read_json_auto('{local_fixture_path}', format='auto')
    """
    )
    con.close()

    extra_env = {
        "OMCAE_DBT_TARGET": "dev",
        "OMCAE_DUCKDB_PATH": str(duckdb_path),
        "OMCAE_USE_LOCAL_BRONZE": "true",
        "OMCAE_BRONZE_PATH": "s3://ofae-data-lakehouse-bronze-dev/otter",
        "OMCAE_PII_SALT": "pr4atestsalt",
    }
    return duckdb_path, profiles_dir, extra_env


@pytest.mark.integration
def test_salted_pii_columns_exist(tmp_path: Path) -> None:
    """dbt build creates the 2 new salted PII columns on silver_orders."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        duckdb_path, profiles_dir, extra_env = _setup_dbt_env(tmp_path, s3)

        success, exc = _dbt_via_dbtRunner(
            DBT_PROJECT, profiles_dir, extra_env=extra_env
        )
        assert success, f"dbt build failed: {exc}"

        con = duckdb.connect(str(duckdb_path))
        try:
            columns = [
                row[0] for row in con.execute("DESCRIBE silver_orders").fetchall()
            ]
            assert "customer_name_hash" in columns, "raw name hash missing"
            assert "customer_phone_hash" in columns, "raw phone hash missing"
            assert (
                "customer_name_hash_salted" in columns
            ), "salted name hash missing"
            assert (
                "customer_phone_hash_salted" in columns
            ), "salted phone hash missing"
        finally:
            con.close()


@pytest.mark.integration
def test_salted_pii_columns_not_null(tmp_path: Path) -> None:
    """Every row has non-null salted hashes."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        duckdb_path, profiles_dir, extra_env = _setup_dbt_env(tmp_path, s3)

        success, exc = _dbt_via_dbtRunner(
            DBT_PROJECT, profiles_dir, extra_env=extra_env
        )
        assert success, f"dbt build failed: {exc}"

        con = duckdb.connect(str(duckdb_path))
        try:
            null_count = con.execute(
                "SELECT COUNT(*) FROM silver_orders "
                "WHERE customer_name_hash_salted IS NULL "
                "   OR customer_phone_hash_salted IS NULL"
            ).fetchone()[0]
            assert null_count == 0, f"Found {null_count} rows with null salted hashes"
        finally:
            con.close()


@pytest.mark.integration
def test_salted_hashes_deterministic_across_runs(tmp_path: Path) -> None:
    """Same salt + same input → identical salted hashes across two runs."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        duckdb_path, profiles_dir, extra_env = _setup_dbt_env(tmp_path, s3)

        # First run
        success1, exc1 = _dbt_via_dbtRunner(
            DBT_PROJECT, profiles_dir, extra_env=extra_env
        )
        assert success1, f"First dbt build failed: {exc1}"

        con = duckdb.connect(str(duckdb_path))
        first_hashes = con.execute(
            "SELECT order_id, customer_name_hash_salted, customer_phone_hash_salted "
            "FROM silver_orders ORDER BY order_id"
        ).fetchall()
        con.close()

        # Second run — same database, same seed
        success2, exc2 = _dbt_via_dbtRunner(
            DBT_PROJECT, profiles_dir, extra_env=extra_env
        )
        assert success2, f"Second dbt build failed: {exc2}"

        con = duckdb.connect(str(duckdb_path))
        second_hashes = con.execute(
            "SELECT order_id, customer_name_hash_salted, customer_phone_hash_salted "
            "FROM silver_orders ORDER BY order_id"
        ).fetchall()
        con.close()

        assert len(first_hashes) == len(second_hashes), (
            f"Row count mismatch: {len(first_hashes)} vs {len(second_hashes)}"
        )
        for (oid1, nh1, ph1), (oid2, nh2, ph2) in zip(
            first_hashes, second_hashes, strict=True
        ):
            assert oid1 == oid2, f"Order mismatch: {oid1} vs {oid2}"
            assert nh1 == nh2, (
                f"Salted name hash changed for {oid1}: {nh1} vs {nh2}"
            )
            assert ph1 == ph2, (
                f"Salted phone hash changed for {oid1}: {ph1} vs {ph2}"
            )


@pytest.mark.integration
def test_raw_hash_columns_preserved(tmp_path: Path) -> None:
    """Raw customer_name_hash and customer_phone_hash still present after PR4a."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        duckdb_path, profiles_dir, extra_env = _setup_dbt_env(tmp_path, s3)

        success, exc = _dbt_via_dbtRunner(
            DBT_PROJECT, profiles_dir, extra_env=extra_env
        )
        assert success, f"dbt build failed: {exc}"

        con = duckdb.connect(str(duckdb_path))
        try:
            raw_nulls = con.execute(
                "SELECT COUNT(*) FROM silver_orders "
                "WHERE customer_name_hash IS NULL "
                "   OR customer_phone_hash IS NULL"
            ).fetchone()[0]
            assert raw_nulls == 0, (
                f"Found {raw_nulls} rows with null raw hash columns "
                f"(back-compat broken)"
            )
        finally:
            con.close()
