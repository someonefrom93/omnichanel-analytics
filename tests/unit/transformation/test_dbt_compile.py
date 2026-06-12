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
