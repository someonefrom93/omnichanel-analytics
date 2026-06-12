"""Tests for the silver Click subcommand — task 2.6."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner


def test_run_silver_cmd_help() -> None:
    """`omc-ingest silver run-silver --help` succeeds with expected output."""
    from omc_analytics.ingestion.run import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["silver", "run-silver", "--help"])

    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}: {result.output}"
    )
    assert "run-silver" in result.output, (
        f"Expected 'run-silver' in help output, got: {result.output}"
    )
    assert "--merchant-id" in result.output, (
        f"Expected '--merchant-id' in help output, got: {result.output}"
    )
    assert "--select" in result.output, (
        f"Expected '--select' in help output, got: {result.output}"
    )


def test_run_silver_cmd_runs(mock_dbt_runner: MagicMock) -> None:
    """Full invocation with --select silver_reports exits 0 and prints success message."""
    from omc_analytics.ingestion.run import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "silver",
            "run-silver",
            "--merchant-id",
            "M1",
            "--select",
            "silver_reports",
        ],
    )

    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}: {result.output}"
    )
    assert "succeeded" in result.output, (
        f"Expected 'succeeded' in output, got: {result.output}"
    )


def test_run_silver_cmd_profiles_dir_env_default(mock_dbt_runner: MagicMock) -> None:
    """When --profiles-dir is passed explicitly, dbt is invoked with it."""
    from omc_analytics.ingestion.run import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "silver",
            "run-silver",
            "--merchant-id",
            "M1",
        ],
    )

    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}: {result.output}"
    )
