"""Smoke test: dbt debug must succeed for dev and prod targets."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _dbt_cmd(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    """Run a dbt CLI command with the venv on PATH."""
    venv_bin = Path(sys.executable).parent
    full_env = {
        **os.environ,
        "PATH": f"{venv_bin}:{os.environ.get('PATH', '')}",
    }
    if env:
        full_env.update(env)
    return subprocess.run(
        ["dbt", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).parent.parent.parent.parent / "dbt_project",
        env=full_env,
    )


@pytest.mark.parametrize("target", ["dev", "prod"])
def test_dbt_debug_succeeds_for_target(target: str, tmp_path: Path) -> None:
    """dbt debug must succeed for both dev and prod targets."""
    # For dev, use a temp DuckDB file to avoid collisions
    duckdb_path = tmp_path / f"{target}.duckdb"
    env = {
        "OMCAE_DBT_TARGET": target,
        "OMCAE_DUCKDB_PATH": str(duckdb_path),
    }
    result = _dbt_cmd("debug", env=env)
    assert result.returncode == 0, (
        f"dbt debug failed for target={target}:\n"
        f"STDOUT: {result.stdout}\n"
        f"STDERR: {result.stderr}"
    )
