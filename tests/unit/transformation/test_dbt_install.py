"""Smoke test: dbt CLI must be reachable after uv sync."""
import os
import subprocess
import sys
from pathlib import Path


def test_dbt_cli_reachable() -> None:
    """The dbt CLI must be on PATH after uv sync."""
    # Use the venv's dbt binary path explicitly to avoid system dbt conflicts
    dbt_path = Path(sys.executable).parent / "dbt"

    # Build env with venv bin directory at front of PATH
    env = {**os.environ, "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '')}"}

    result = subprocess.run(
        [str(dbt_path), "--version"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, f"dbt --version failed: {result.stderr}"
    assert "Core:" in result.stdout, f"dbt core component not in output: {result.stdout}"
    assert "duckdb" in result.stdout.lower(), f"dbt-duckdb plugin not in output: {result.stdout}"
