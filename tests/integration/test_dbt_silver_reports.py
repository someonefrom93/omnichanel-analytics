"""End-to-end integration test for the silver_reports dbt model.

Pre-seeds moto S3 with Bronze report fixture objects (enqueue + result),
runs dbt build via dbtRunner in-process, and asserts the silver_reports
Parquet is materialized with the expected row and financial aggregates.

Opt-in via `pytest -m integration` — skipped by default.

DEVIATION NOTE (PR3b):
    Same S3 mocking limitation as PR3a: DuckDB httpfs makes real HTTPS
    calls that moto (boto3-only) does not intercept. The workaround mirrors
    PR3a: pre-create bronze.reports_enqueue and bronze.reports_result
    tables in DuckDB using boto3-fetched fixture files, then set
    OMCAE_USE_LOCAL_BRONZE=true so the model reads from the local tables
    rather than the S3 sources.
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
ENQUEUE_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "otter" / "reports_enqueue_response.json"
)
RESULT_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "otter" / "reports_result_ready.json"
)
DBT_PROJECT = REPO_ROOT / "dbt_project"

BRONZE_BUCKET = "ofae-data-lakehouse-bronze-dev"

# Hive-partitioned Bronze paths for the fixtures
ENQUEUE_KEY = (
    "otter/merchant_id=merchant_001/"
    "year=2026/month=06/day=10/"
    "reports_enqueue-20260610T120000Z.json"
)
RESULT_KEY = (
    "otter/merchant_id=merchant_001/"
    "year=2026/month=06/day=10/"
    "reports_result-20260610T120000Z.json"
)


def _dbt_via_dbtRunner(
    project_dir: Path,
    profiles_dir: Path,
    select: str = "silver_reports",
    extra_env: dict | None = None,
) -> tuple[bool, str]:
    """Run dbt build via dbtRunner in-process.

    Returns (success, exception_message_or_empty_string).
    """
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
    s3_client: boto3.client,
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


@pytest.mark.integration
def test_silver_reports_e2e_with_moto_s3(tmp_path: Path) -> None:
    """Run silver_reports end-to-end against moto S3 + a real DuckDB.

    The test:
    1. Pre-seeds moto S3 with the reports fixtures at Bronze Hive paths.
    2. Sets up a temp DuckDB file and dbt profile.
    3. Pre-creates bronze.reports_enqueue and bronze.reports_result tables
       in DuckDB by fetching fixtures from moto S3 via boto3.
    4. Invokes dbt build via dbtRunner in-process.
    5. Asserts silver_reports has 1 row with job_id='job_abc123' and the
       expected financial aggregates (gross_sales_amount=12500,
       net_payout_amount=8750).
    """
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")

        try:
            s3.create_bucket(Bucket=BRONZE_BUCKET)
        except Exception:
            pass  # Bucket may already exist

        # Write enqueue fixture to moto S3
        enqueue_body = json.dumps(
            {
                k: v
                for k, v in json.loads(ENQUEUE_FIXTURE.read_text()).items()
                if k not in ("source", "version", "endpoint")
            }
        )
        s3.put_object(Bucket=BRONZE_BUCKET, Key=ENQUEUE_KEY, Body=enqueue_body)

        # Write result fixture to moto S3
        result_body = json.dumps(
            {
                k: v
                for k, v in json.loads(RESULT_FIXTURE.read_text()).items()
                if k not in ("source", "version", "endpoint")
            }
        )
        s3.put_object(Bucket=BRONZE_BUCKET, Key=RESULT_KEY, Body=result_body)

        # Set up temp DuckDB and profile
        duckdb_path = tmp_path / "silver_reports_e2e.duckdb"
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

        # Temp dir for fixture files fetched from moto S3
        moto_fetch_dir = tmp_path / "moto_fetch"
        moto_fetch_dir.mkdir()

        con = duckdb.connect(str(duckdb_path))
        con.execute("CREATE SCHEMA IF NOT EXISTS bronze")

        # Fetch enqueue fixture from moto S3 via boto3
        local_enqueue_path = _fetch_fixture_from_moto(
            s3, BRONZE_BUCKET, ENQUEUE_KEY, moto_fetch_dir
        )
        con.execute(
            f"""
            CREATE OR REPLACE TABLE bronze.reports_enqueue AS
            SELECT * FROM read_json_auto('{local_enqueue_path}', format='auto')
        """
        )

        enqueue_count = con.execute(
            "SELECT COUNT(*) FROM bronze.reports_enqueue"
        ).fetchone()[0]
        assert (
            enqueue_count == 1
        ), f"Expected 1 row in bronze.reports_enqueue, got {enqueue_count}"

        # Fetch result fixture from moto S3 via boto3
        local_result_path = _fetch_fixture_from_moto(
            s3, BRONZE_BUCKET, RESULT_KEY, moto_fetch_dir
        )
        con.execute(
            f"""
            CREATE OR REPLACE TABLE bronze.reports_result AS
            SELECT * FROM read_json_auto('{local_result_path}', format='auto')
        """
        )

        result_count = con.execute(
            "SELECT COUNT(*) FROM bronze.reports_result"
        ).fetchone()[0]
        assert (
            result_count == 1
        ), f"Expected 1 row in bronze.reports_result, got {result_count}"
        con.close()

        # Run dbt build via dbtRunner
        # OMCAE_USE_LOCAL_BRONZE=true bypasses S3 source reads and uses
        # the pre-seeded bronze tables directly.
        success, exception_msg = _dbt_via_dbtRunner(
            DBT_PROJECT,
            profiles_dir,
            extra_env={
                "OMCAE_DBT_TARGET": "dev",
                "OMCAE_DUCKDB_PATH": str(duckdb_path),
                "OMCAE_USE_LOCAL_BRONZE": "true",
                "OMCAE_BRONZE_PATH": "s3://ofae-data-lakehouse-bronze-dev/otter",
            },
        )

        assert (
            success
        ), f"dbt build failed for silver_reports.\nException: {exception_msg}"

        # Verify the silver_reports table
        con = duckdb.connect(str(duckdb_path))
        try:
            row_count = con.execute("SELECT COUNT(*) FROM silver_reports").fetchone()[0]

            assert row_count == 1, (
                f"Expected 1 row in silver_reports "
                f"(one row per report job), got {row_count}"
            )

            columns = [
                row[0] for row in con.execute("DESCRIBE silver_reports").fetchall()
            ]
            required_cols = [
                "job_id",
                "merchant_id",
                "result_status",
                "gross_sales_amount",
                "net_payout_amount",
            ]
            for col in required_cols:
                assert col in columns, f"Missing required column: {col}"

            # Spot-check: verify job_id and financial amounts from the fixture
            row = con.execute(
                "SELECT job_id, merchant_id, result_status, "
                "gross_sales_amount, net_payout_amount "
                "FROM silver_reports"
            ).fetchone()

            assert (
                row[0] == "job_abc123"
            ), f"job_id: expected 'job_abc123', got {row[0]}"
            assert (
                row[1] == "store_001"
            ), f"merchant_id: expected 'store_001', got {row[1]}"
            assert row[2] == "READY", f"result_status: expected 'READY', got {row[2]}"
            assert row[3] == 12500, f"gross_sales_amount: expected 12500, got {row[3]}"
            assert row[4] == 8750, f"net_payout_amount: expected 8750, got {row[4]}"

        finally:
            con.close()
