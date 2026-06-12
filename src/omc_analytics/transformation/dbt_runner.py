"""Python wrapper around dbt-core's dbtRunner API.

Invokes `dbt build` in-process with a controlled stdlib logging.Handler
that streams dbt's own log lines into the Python logger. Emits a single
LogsPort row (STARTED → SUCCESS/FAILED) wrapping the run.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from dbt.cli.main import dbtRunner  # type: ignore[import-not-found]

from omc_analytics.common.logs import LogsPort, RunLog

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DbtRunResult:
    success: bool
    elapsed_seconds: float
    exception: BaseException | None = None


@contextmanager
def _dbt_logging_handler() -> Iterator[logging.Handler]:
    """Context manager: attach a stdlib Handler to dbt's 'dbt' logger.

    Captures dbt's own log lines and routes them to _logger. Removed in
    finally to prevent handler leak across dbtRunner() invocations.
    """
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(levelname)s dbt: %(message)s"))
    dbt_logger = logging.getLogger("dbt")
    dbt_logger.addHandler(handler)
    previous_level = dbt_logger.level
    dbt_logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        dbt_logger.removeHandler(handler)
        dbt_logger.setLevel(previous_level)


def run_dbt_build(
    project_dir: Path,
    profiles_dir: Path,
    *,
    select: list[str] | None = None,
    vars: dict | None = None,
    logs_port: LogsPort | None = None,
    merchant_id: str | None = None,
    pipeline_name: Literal["silver_transformation"] = "silver_transformation",
) -> DbtRunResult:
    """Run `dbt build` in-process. Optionally write a LogsPort row."""
    run_id = uuid.uuid4()
    started_at = datetime.now(UTC)
    if logs_port is not None:
        logs_port.insert_started(RunLog(
            id=run_id, merchant_id=merchant_id or "n/a", run_id=run_id,
            pipeline_name=pipeline_name, status="STARTED",
            started_at=started_at, finished_at=None, error_class=None, error_message=None,
        ))
    args = ["build", "--project-dir", str(project_dir), "--profiles-dir", str(profiles_dir)]
    if select:
        args.extend(["--select", " ".join(select)])
    if vars:
        for k, v in vars.items():
            args.extend(["--vars", f"{k}: {_to_json(v)}"])
    exception: BaseException | None = None
    success = False
    started = datetime.now(UTC)
    with _dbt_logging_handler():
        try:
            runner = dbtRunner()
            result = runner.invoke(args)
            success = bool(result.success)
        except BaseException as exc:
            exception = exc
            success = False
    elapsed = (datetime.now(UTC) - started).total_seconds()
    if logs_port is not None:
        logs_port.update_finished(
            run_id=run_id,
            status="SUCCESS" if success else "FAILED",
            error_class=type(exception).__name__ if exception else None,
            error_message=str(exception) if exception else None,
        )
    return DbtRunResult(success=success, elapsed_seconds=elapsed, exception=exception)


def _to_json(value: object) -> str:
    return json.dumps(value)
