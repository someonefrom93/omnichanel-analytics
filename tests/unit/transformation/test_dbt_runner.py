"""Tests for dbt_runner — task 2.5."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestDbtLoggingHandler:
    """Unit tests for the _dbt_logging_handler context manager."""

    def test_dbt_logging_handler_attach_detach(self) -> None:
        """Context manager attaches one handler and detaches it in finally."""
        from omc_analytics.transformation.dbt_runner import _dbt_logging_handler

        dbt_logger = logging.getLogger("dbt")
        # Count handlers before
        before = len(dbt_logger.handlers)

        with _dbt_logging_handler():
            # Should have exactly one more handler while inside context
            during = len(dbt_logger.handlers)
            assert (
                during == before + 1
            ), f"Expected {before + 1} handlers during context, got {during}"

        # After exiting, handler count returns to before
        after = len(dbt_logger.handlers)
        assert after == before, (
            f"Expected {before} handlers after context, got {after}; "
            "handler leak detected"
        )


class TestRunDbtBuild:
    """Unit tests for run_dbt_build with LogsPort lifecycle."""

    def test_run_dbt_build_writes_logs_port_row(self) -> None:
        """run_dbt_build writes STARTED then SUCCESS row via LogsPort."""
        from omc_analytics.common.logs import InMemoryLogs
        from omc_analytics.transformation.dbt_runner import run_dbt_build

        logs = InMemoryLogs()
        mock_result = MagicMock()
        mock_result.success = True

        with patch(
            "omc_analytics.transformation.dbt_runner.dbtRunner"
        ) as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner.invoke.return_value = mock_result
            mock_runner_cls.return_value = mock_runner

            result = run_dbt_build(
                project_dir=Path("/fake/dbt_project"),
                profiles_dir=Path("/fake/profiles"),
                logs_port=logs,
                merchant_id="M1",
            )

        assert result.success is True, "Expected success=True"
        assert result.exception is None, "Expected no exception"

        rows = logs.get_all()
        assert len(rows) == 1, f"Expected 1 log row, got {len(rows)}"
        assert rows[0].status == "SUCCESS", f"Expected SUCCESS, got {rows[0].status}"
        assert rows[0].error_class is None, "Expected no error_class on SUCCESS"

    def test_run_dbt_build_writes_failed_row_on_exception(self) -> None:
        """run_dbt_build writes FAILED row when dbtRunner raises an exception."""
        from omc_analytics.common.logs import InMemoryLogs
        from omc_analytics.transformation.dbt_runner import run_dbt_build

        logs = InMemoryLogs()

        with patch(
            "omc_analytics.transformation.dbt_runner.dbtRunner"
        ) as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner.invoke.side_effect = RuntimeError("dbt runner failed")
            mock_runner_cls.return_value = mock_runner

            result = run_dbt_build(
                project_dir=Path("/fake/dbt_project"),
                profiles_dir=Path("/fake/profiles"),
                logs_port=logs,
                merchant_id="M1",
            )

        assert result.success is False, "Expected success=False"
        assert result.exception is not None, "Expected an exception"
        assert isinstance(result.exception, RuntimeError)

        rows = logs.get_all()
        assert len(rows) == 1, f"Expected 1 log row, got {len(rows)}"
        assert rows[0].status == "FAILED", f"Expected FAILED, got {rows[0].status}"
        assert (
            rows[0].error_class == "RuntimeError"
        ), f"Expected error_class='RuntimeError', got {rows[0].error_class!r}"
        assert rows[0].error_message is not None, "Expected error_message on FAILED"
