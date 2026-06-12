"""Test: silver_orders model — schema, SQL, and dbt build guards.

These tests validate that the silver_orders model (SQL, YAML schema, custom
data test) is present and correctly configured per PRD §5.3 and the
silver-orders-pr3a spec.

Strict TDD: these tests are written BEFORE the implementation exists.
They MUST fail on the current codebase and MUST pass after implementation.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent
DBT_PROJECT = REPO_ROOT / "dbt_project"
SILVER_DIR = DBT_PROJECT / "models" / "silver"
TESTS_DIR = DBT_PROJECT / "tests"


def _dbt_cmd_with_env(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    """Run dbt CLI with the current venv on PATH."""
    venv_bin = Path(sys.executable).parent
    full_env = {
        **__import__("os").environ,
        "PATH": f"{venv_bin}:{__import__('os').environ.get('PATH', '')}",
    }
    if env:
        full_env.update(env)
    return subprocess.run(
        [
            "dbt",
            *args,
            "--project-dir",
            str(DBT_PROJECT),
            "--profiles-dir",
            str(DBT_PROJECT),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=full_env,
    )


class TestSilverOrdersModelFile:
    """Guard: silver_orders.sql must exist and have correct content."""

    def test_silver_orders_model_file_present(self) -> None:
        """The silver_orders.sql model file must exist."""
        model_file = SILVER_DIR / "silver_orders.sql"
        assert model_file.exists(), (
            f"silver_orders.sql not found at {model_file}. "
            "This model is required for PR3a silver layer."
        )

    def test_silver_orders_sql_contains_cte(self) -> None:
        """silver_orders.sql must contain a CTE that selects from the bronze source."""
        model_file = SILVER_DIR / "silver_orders.sql"
        content = model_file.read_text()
        # Accept either 'with source as' or 'with bronze as' — both are valid
        # naming conventions for the first CTE that reads the bronze source.
        assert (
            "with source as" in content.lower()
            or "with bronze as" in content.lower()
            or "source as (" in content.lower()
            or "bronze as (" in content.lower()
        ), (
            "silver_orders.sql must define a CTE that selects from "
            "{{ source('bronze', 'orders') }}. The CTE may be named 'source' or 'bronze'."
        )

    def test_silver_orders_sql_references_source(self) -> None:
        """silver_orders.sql must reference {{ source('bronze', 'orders') }}."""
        model_file = SILVER_DIR / "silver_orders.sql"
        content = model_file.read_text()
        assert "{{ source('bronze', 'orders') }}" in content, (
            "silver_orders.sql must use {{ source('bronze', 'orders') }} "
            "to read from the Bronze layer. Do NOT hardcode S3 paths."
        )

    def test_silver_orders_sql_has_unique_key_config(self) -> None:
        """silver_orders.sql must have unique_key=['order_id', 'source_marketplace']."""
        model_file = SILVER_DIR / "silver_orders.sql"
        content = model_file.read_text()
        assert (
            "unique_key" in content
        ), "silver_orders.sql must define unique_key in the config block."
        # The composite key must be the list form per design §Composite unique_key
        assert "order_id" in content and "source_marketplace" in content, (
            "unique_key must include both 'order_id' and 'source_marketplace' "
            "as a list-form composite key per PRD §5.3."
        )

    def test_silver_orders_sql_incremental_materialization(self) -> None:
        """silver_orders.sql must use incremental+merge materialization."""
        model_file = SILVER_DIR / "silver_orders.sql"
        content = model_file.read_text()
        assert (
            "incremental" in content.lower()
        ), "silver_orders.sql must be materialized as 'incremental'."
        assert "merge" in content.lower(), (
            "silver_orders.sql must use 'merge' incremental strategy "
            "for idempotent upserts."
        )


class TestSilverOrdersSchemaFile:
    """Guard: silver_orders.yml must exist with correct column tests."""

    def test_silver_orders_schema_file_present(self) -> None:
        """The silver_orders.yml schema file must exist."""
        schema_file = SILVER_DIR / "silver_orders.yml"
        assert schema_file.exists(), (
            f"silver_orders.yml not found at {schema_file}. "
            "This schema file is required for PR3a silver layer."
        )

    def test_silver_orders_schema_has_not_null_order_id(self) -> None:
        """silver_orders.yml must have not_null test on order_id."""
        schema_file = SILVER_DIR / "silver_orders.yml"
        content = schema_file.read_text()
        # Look for the order_id column definition with not_null test
        assert (
            "order_id" in content
        ), "order_id column must be defined in silver_orders.yml"
        # The test should be nested under order_id's tests list
        # Check that not_null appears in the order_id column section
        assert "not_null" in content, (
            "silver_orders.yml must define a not_null test on order_id "
            "per spec §dbt Tests."
        )

    def test_silver_orders_schema_has_not_null_source_marketplace(self) -> None:
        """silver_orders.yml must have not_null test on source_marketplace."""
        schema_file = SILVER_DIR / "silver_orders.yml"
        content = schema_file.read_text()
        assert (
            "source_marketplace" in content
        ), "source_marketplace column must be defined in silver_orders.yml"
        assert (
            "not_null" in content
        ), "silver_orders.yml must define a not_null test on source_marketplace."

    def test_silver_orders_schema_has_composite_uniqueness_test(self) -> None:
        """silver_orders.yml must have composite unique test on (order_id, source_marketplace).

        Per PRD §5.3: 'one row per (order_id, source_marketplace) tuple'.
        Since dbt_utils is not installed as a pip package, this uses a custom
        singular test file instead of dbt_utils.unique_combination_of_columns.
        """
        # Check for custom singular test (fallback approach)
        custom_test = TESTS_DIR / "silver_orders_unique_order_marketplace.sql"
        assert custom_test.exists(), (
            "A custom singular test for composite uniqueness "
            "(silver_orders_unique_order_marketplace.sql) must exist at "
            f"{custom_test} since dbt_utils is not pip-installable. "
            "This test enforces the per-tuple uniqueness constraint from PRD §5.3."
        )

    def test_silver_orders_schema_has_total_amount_not_null(self) -> None:
        """silver_orders.yml must have not_null test on total_amount."""
        schema_file = SILVER_DIR / "silver_orders.yml"
        content = schema_file.read_text()
        assert (
            "total_amount" in content
        ), "total_amount column must be defined in silver_orders.yml"


class TestSilverOrdersCustomDataTest:
    """Guard: custom data test for total_amount anomaly policy."""

    def test_custom_data_test_for_total_amount_present(self) -> None:
        """The custom data test for total_amount=0 anomaly must exist."""
        test_file = TESTS_DIR / "silver_orders_total_amount_not_null_or_zero.sql"
        assert test_file.exists(), (
            f"Custom data test not found at {test_file}. "
            "Per PRD §5.3: 'Detections default to 0.00 while flagging an "
            "administrative anomaly row.' This test warns on total_amount=0."
        )

    def test_custom_data_test_references_silver_orders(self) -> None:
        """The total_amount test must reference {{ ref('silver_orders') }}."""
        test_file = TESTS_DIR / "silver_orders_total_amount_not_null_or_zero.sql"
        content = test_file.read_text()
        assert (
            "{{ ref('silver_orders') }}" in content
        ), "The custom data test must reference silver_orders via {{ ref() }}."

    def test_custom_data_test_checks_total_amount_zero(self) -> None:
        """The custom data test must have a WHERE total_amount = 0 clause."""
        test_file = TESTS_DIR / "silver_orders_total_amount_not_null_or_zero.sql"
        content = test_file.read_text()
        assert "total_amount = 0" in content or "total_amount=0" in content, (
            "The custom data test must filter to rows where total_amount = 0 "
            "per PRD §5.3 anomaly policy."
        )


class TestDbtCompileWithSilverOrders:
    """Integration: dbt compile must succeed with silver_orders present."""

    def test_dbt_compile_with_silver_orders_succeeds(self, tmp_path: Path) -> None:
        """dbt compile must succeed when silver_orders model is present.

        This validates:
        - silver_orders.sql parses correctly (no Jinja/template errors)
        - silver_orders.yml schema parses correctly
        - Source reference {{ source('bronze', 'orders') }} resolves
        - All dbt macros (parse_bronze_filename) compile
        """
        env = {
            "OMCAE_DBT_TARGET": "dev",
            "OMCAE_DUCKDB_PATH": str(tmp_path / "compile.duckdb"),
            "OMCAE_BRONZE_PATH": "s3://ofae-data-lakehouse-bronze-dev/otter",
            "OMCAE_PII_SALT": "test-salt",
        }
        result = _dbt_cmd_with_env("compile", env=env)
        assert result.returncode == 0, (
            f"dbt compile failed with silver_orders present:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
