"""Test: dbt compile + parse_bronze_filename macro presence.

These tests validate that the dbt project configuration (sources.yml + macros)
parses correctly and the macro SQL is well-formed.
"""

import os
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
    """Run dbt CLI with the venv on PATH."""
    venv_bin = Path(sys.executable).parent
    full_env = {
        **os.environ,
        "PATH": f"{venv_bin}:{os.environ.get('PATH', '')}",
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


def test_dbt_compile_succeeds(tmp_path: Path) -> None:
    """dbt compile must succeed (validates source YAML + macro SQL parse).

    This is a syntactic + semantic check; it does NOT require S3 access
    because sources.yml uses templated external_location that compiles fine
    without actual data.
    """
    env = {
        "OMCAE_DBT_TARGET": "dev",
        "OMCAE_DUCKDB_PATH": str(tmp_path / "compile.duckdb"),
        "OMCAE_BRONZE_PATH": "s3://ofae-data-lakehouse-bronze-dev/otter",
    }
    result = _dbt_cmd_with_env("compile", env=env)
    # dbt compile succeeds only if:
    # 1. All YAML files parse (no Jinja/template errors)
    # 2. All SQL macro files parse
    # 3. Source references resolve
    assert (
        result.returncode == 0
    ), f"dbt compile failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"


def test_parse_bronze_filename_macro_file_present() -> None:
    """The parse_bronze_filename macro file must exist and contain expected SQL.

    This is a cheap guard that the macro file exists and has the key SQL
    fragments before we run a full dbt compile.
    """
    macro_file = DBT_PROJECT / "macros" / "parse_bronze_filename.sql"
    assert macro_file.exists(), f"Macro file not found: {macro_file}"
    content = macro_file.read_text()
    assert "regexp_extract" in content, "Macro must use regexp_extract for DuckDB"
    assert (
        "STRUCT_PACK" in content
    ), "Macro must use STRUCT_PACK for struct construction"
    assert "target_date" in content, "Macro must output target_date field"
    assert "run_timestamp_utc" in content, "Macro must output run_timestamp_utc field"


class TestDbtCompileWithSilverReports:
    """Guard: silver_reports model must be present and compile cleanly."""

    def test_silver_reports_model_file_present(self) -> None:
        """silver_reports.sql must exist with incremental+merge and unique_key='job_id'."""
        model_file = SILVER_DIR / "silver_reports.sql"
        assert model_file.exists(), (
            f"silver_reports.sql not found at {model_file}. "
            "This model is required for PR3b silver_reports."
        )
        content = model_file.read_text()
        assert (
            "unique_key" in content
        ), "silver_reports.sql must define unique_key in the config block."
        assert (
            "job_id" in content
        ), "unique_key must be 'job_id' per spec §Materialization."
        # Must have a join CTE between enqueue and result sources
        assert (
            "enqueue" in content.lower() and "result" in content.lower()
        ), "silver_reports.sql must have CTEs for enqueue and result sources."
        assert (
            "incremental" in content.lower()
        ), "silver_reports.sql must use incremental materialization."

    def test_silver_reports_schema_file_present(self) -> None:
        """silver_reports.yml must exist with not_null and unique on job_id."""
        schema_file = SILVER_DIR / "silver_reports.yml"
        assert schema_file.exists(), (
            f"silver_reports.yml not found at {schema_file}. "
            "This schema file is required for PR3b silver_reports."
        )
        content = schema_file.read_text()
        assert (
            "job_id" in content
        ), "job_id column must be defined in silver_reports.yml"
        assert (
            "not_null" in content
        ), "silver_reports.yml must define not_null test on job_id per spec §dbt Tests."
        assert (
            "unique" in content
        ), "silver_reports.yml must define unique test on job_id per spec §dbt Tests."

    def test_dbt_compile_with_silver_reports_succeeds(self, tmp_path: Path) -> None:
        """dbt compile must succeed when silver_reports model is present.

        This validates:
        - silver_reports.sql parses correctly (no Jinja/template errors)
        - silver_reports.yml schema parses correctly
        - Source references bronze.reports_enqueue and bronze.reports_result resolve
        - All dbt macros compile
        """
        env = {
            "OMCAE_DBT_TARGET": "dev",
            "OMCAE_DUCKDB_PATH": str(tmp_path / "compile.duckdb"),
            "OMCAE_BRONZE_PATH": "s3://ofae-data-lakehouse-bronze-dev/otter",
        }
        result = _dbt_cmd_with_env("compile", env=env)
        assert result.returncode == 0, (
            f"dbt compile failed with silver_reports present:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
