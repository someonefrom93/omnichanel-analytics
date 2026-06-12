"""Click sub-group for the Silver transformation layer."""

from __future__ import annotations

import os
from pathlib import Path

import click

from omc_analytics.common.logs import InMemoryLogs
from omc_analytics.transformation.dbt_runner import run_dbt_build

REPO_ROOT = Path(__file__).resolve().parents[3]
DBT_PROJECT = REPO_ROOT / "dbt_project"


@click.group(name="silver")
def silver_group() -> None:
    """Silver transformation commands (dbt)."""


@silver_group.command(name="run-silver")
@click.option(
    "--env",
    type=click.Choice(["dev", "staging", "prod"]),
    default="dev",
    show_default=True,
    help="Target environment (selects the dbt profile target and S3 bucket).",
)
@click.option(
    "--select",
    multiple=True,
    help="dbt --select models to build (repeatable). Default: all silver models.",
)
@click.option(
    "--merchant-id",
    default=None,
    help="Optional merchant_id for the LogsPort row.",
)
@click.option(
    "--profiles-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=Path(os.environ.get("OMCAE_DBT_PROFILES_DIR", str(DBT_PROJECT))),
    show_default=True,
)
def run_silver_cmd(
    env: str, select: tuple[str, ...], merchant_id: str | None, profiles_dir: Path
) -> None:
    """Run dbt build for the Silver layer."""
    os.environ["OMCAE_DBT_TARGET"] = env
    logs = InMemoryLogs()
    result = run_dbt_build(
        project_dir=DBT_PROJECT,
        profiles_dir=profiles_dir,
        select=list(select) if select else None,
        logs_port=logs,
        merchant_id=merchant_id,
    )
    if not result.success:
        raise click.ClickException(
            f"dbt build failed after {result.elapsed_seconds:.1f}s"
        )
    click.echo(f"dbt build succeeded in {result.elapsed_seconds:.1f}s")
