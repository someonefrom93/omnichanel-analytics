"""Integration test for the Gold star schema (PR4b).

Pre-seeds moto S3 with the PR1 Bronze fixture, runs dbt seed + build
for dim_menu_catalog and fact_financial_sales via dbtRunner in-process,
and asserts row counts and margin arithmetic.

Opt-in via `pytest -m integration` — skipped by default.
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
    select: str,
    extra_env: dict | None = None,
) -> tuple[bool, str]:
    """Run dbt (build/seed) via dbtRunner in-process.

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


def _dbt_seed_via_dbtRunner(
    project_dir: Path,
    profiles_dir: Path,
    extra_env: dict | None = None,
) -> tuple[bool, str]:
    """Run dbt seed via dbtRunner in-process."""
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
            "seed",
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
def test_gold_star_schema_e2e(tmp_path: Path) -> None:
    """Run Gold star schema end-to-end: seed + dim + fact + tests.

    Validates:
    - dim_menu_catalog: 2 rows (BURGER_CLASSIC, FRIES_MEDIUM)
    - fact_financial_sales: 2 rows with correct margin arithmetic
    - dbt tests pass (not_null PKs, dim uniqueness)
    """
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")

        try:
            s3.create_bucket(Bucket=BRONZE_BUCKET)
        except Exception:
            pass

        # Pre-seed moto S3 with the PR1 fixture
        fixture_raw = json.loads(FIXTURE.read_text())
        fixture_body = json.dumps(
            {
                k: v
                for k, v in fixture_raw.items()
                if k not in ("source", "version", "endpoint")
            }
        )
        s3.put_object(Bucket=BRONZE_BUCKET, Key=BRONZE_KEY, Body=fixture_body)

        # Temp DuckDB + dbt profile
        duckdb_path = tmp_path / "gold_e2e.duckdb"
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

        # Pre-seed bronze.orders (same pattern as silver_orders e2e test)
        con = duckdb.connect(str(duckdb_path))
        con.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        con.execute("CREATE SCHEMA IF NOT EXISTS silver")
        local_fixture_path = _fetch_fixture_from_moto(
            s3, BRONZE_BUCKET, BRONZE_KEY, moto_fetch_dir
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
            "OMCAE_PII_SALT": "test-salt",
        }

        # Step 1: Build silver_orders first (Gold depends on it)
        success, exc = _dbt_via_dbtRunner(
            DBT_PROJECT, profiles_dir, select="silver_orders", extra_env=extra_env
        )
        assert success, f"dbt build silver_orders failed: {exc}"

        # Step 2: Seed merchant_cogs
        seed_success, seed_exc = _dbt_seed_via_dbtRunner(
            DBT_PROJECT, profiles_dir, extra_env=extra_env
        )
        assert seed_success, f"dbt seed failed: {seed_exc}"

        # Step 3: Build Gold models (dim + fact + tests)
        gold_success, gold_exc = _dbt_via_dbtRunner(
            DBT_PROJECT,
            profiles_dir,
            select="dim_menu_catalog fact_financial_sales",
            extra_env=extra_env,
        )
        assert gold_success, f"dbt build Gold failed: {gold_exc}"

        # Assertions
        con = duckdb.connect(str(duckdb_path))
        try:
            # dim_menu_catalog: 2 unique SKUs
            dim_count = con.execute("SELECT COUNT(*) FROM dim_menu_catalog").fetchone()[
                0
            ]
            assert (
                dim_count == 2
            ), f"Expected 2 rows in dim_menu_catalog, got {dim_count}"

            dim_cols = [
                row[0] for row in con.execute("DESCRIBE dim_menu_catalog").fetchall()
            ]
            for col in (
                "merchant_id",
                "line_item_sku",
                "line_item_name",
                "first_seen_at",
                "last_seen_at",
            ):
                assert col in dim_cols, f"dim_menu_catalog missing column: {col}"

            # fact_financial_sales: 2 rows (one per line item)
            fact_count = con.execute(
                "SELECT COUNT(*) FROM fact_financial_sales"
            ).fetchone()[0]
            assert (
                fact_count == 2
            ), f"Expected 2 rows in fact_financial_sales, got {fact_count}"

            fact_cols = [
                row[0]
                for row in con.execute("DESCRIBE fact_financial_sales").fetchall()
            ]
            for col in (
                "merchant_id",
                "order_id",
                "source_marketplace",
                "line_item_sku",
                "gross_order_value",
                "estimated_marketplace_commission",
                "calculated_recipe_cogs",
                "packaging_cost",
                "true_net_payout_margin",
            ):
                assert col in fact_cols, f"fact_financial_sales missing column: {col}"

            # Verify margin arithmetic for ord_001 / BURGER_CLASSIC
            # gross=2500, commission=15%×2500=375, cogs=800, pack=100
            # margin = 2500 - 375 - 800 - 100 = 1225
            margin_rows = con.execute(
                "SELECT order_id, line_item_sku, gross_order_value, "
                "estimated_marketplace_commission, calculated_recipe_cogs, "
                "packaging_cost, true_net_payout_margin "
                "FROM fact_financial_sales "
                "ORDER BY order_id"
            ).fetchall()

            assert len(margin_rows) == 2

            # ord_001: BURGER_CLASSIC, gross=2500
            ord_001 = margin_rows[0]
            assert ord_001[0] == "ord_001"
            assert ord_001[1] == "BURGER_CLASSIC"
            assert ord_001[2] == 2500, f"ord_001 gross: {ord_001[2]}"
            assert ord_001[3] == 375, f"ord_001 commission: {ord_001[3]}"
            assert ord_001[4] == 800, f"ord_001 recipe_cogs: {ord_001[4]}"
            assert ord_001[5] == 100, f"ord_001 packaging: {ord_001[5]}"
            assert ord_001[6] == 1225, f"ord_001 margin: {ord_001[6]}"

            # ord_002: FRIES_MEDIUM, gross=1800
            # commission=15%×1800=270, cogs=300, pack=50
            # margin = 1800 - 270 - 300 - 50 = 1180
            ord_002 = margin_rows[1]
            assert ord_002[0] == "ord_002"
            assert ord_002[1] == "FRIES_MEDIUM"
            assert ord_002[2] == 1800, f"ord_002 gross: {ord_002[2]}"
            assert ord_002[3] == 270, f"ord_002 commission: {ord_002[3]}"
            assert ord_002[4] == 300, f"ord_002 recipe_cogs: {ord_002[4]}"
            assert ord_002[5] == 50, f"ord_002 packaging: {ord_002[5]}"
            assert ord_002[6] == 1180, f"ord_002 margin: {ord_002[6]}"

        finally:
            con.close()
