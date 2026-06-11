"""Tests for LogsPort Protocol and InMemoryLogs implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from omc_analytics.common.logs import (
    InMemoryLogs,
    LogsPort,
    RunLog,
    RunNotFoundError,
)


class TestRunLog:
    """Test RunLog pydantic model validation."""

    def test_valid_run_log_all_fields(self) -> None:
        """All fields accepted when valid."""
        run_id = uuid4()
        log = RunLog(
            id=uuid4(),
            merchant_id="merchant_001",
            run_id=run_id,
            pipeline_name="otter_bronze_ingestion",
            status="STARTED",
            started_at=datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC),
            finished_at=None,
            error_class=None,
            error_message=None,
        )
        assert log.merchant_id == "merchant_001"
        assert log.run_id == run_id
        assert log.status == "STARTED"

    def test_valid_run_log_finished(self) -> None:
        """finished_at and error fields populated on SUCCESS."""
        run_id = uuid4()
        started = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        finished = datetime(2026, 6, 10, 2, 5, 30, tzinfo=UTC)
        log = RunLog(
            id=uuid4(),
            merchant_id="merchant_001",
            run_id=run_id,
            pipeline_name="otter_bronze_ingestion",
            status="SUCCESS",
            started_at=started,
            finished_at=finished,
            error_class=None,
            error_message=None,
        )
        assert log.status == "SUCCESS"
        assert log.finished_at == finished

    def test_valid_run_log_failed(self) -> None:
        """FAILED status with error_class and error_message."""
        run_id = uuid4()
        started = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        finished = datetime(2026, 6, 10, 2, 1, 0, tzinfo=UTC)
        log = RunLog(
            id=uuid4(),
            merchant_id="merchant_001",
            run_id=run_id,
            pipeline_name="otter_bronze_ingestion",
            status="FAILED",
            started_at=started,
            finished_at=finished,
            error_class="RateLimitExceededError",
            error_message="429 after 3 retries",
        )
        assert log.status == "FAILED"
        assert log.error_class == "RateLimitExceededError"

    def test_rejects_invalid_status_literal(self) -> None:
        """Status must be one of STARTED, SUCCESS, FAILED."""
        with pytest.raises(ValidationError):
            RunLog(
                id=uuid4(),
                merchant_id="merchant_001",
                run_id=uuid4(),
                pipeline_name="otter_bronze_ingestion",
                status="INVALID",
                started_at=datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC),
            )

    def test_rejects_invalid_pipeline_name(self) -> None:
        """Pipeline name must be otter_bronze_ingestion."""
        with pytest.raises(ValidationError):
            RunLog(
                id=uuid4(),
                merchant_id="merchant_001",
                run_id=uuid4(),
                pipeline_name="other_pipeline",
                status="STARTED",
                started_at=datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC),
            )


class TestLogsPortProtocol:
    """Test LogsPort Protocol interface."""

    def test_insert_started_returns_run_id(self) -> None:
        """insert_started returns the run_id from the row."""
        impl = InMemoryLogs()
        run_id = uuid4()
        row = RunLog(
            id=uuid4(),
            merchant_id="merchant_001",
            run_id=run_id,
            pipeline_name="otter_bronze_ingestion",
            status="STARTED",
            started_at=datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC),
            finished_at=None,
            error_class=None,
            error_message=None,
        )
        result = impl.insert_started(row)
        assert result == run_id

    def test_update_finished_sets_status_and_finished_at(self) -> None:
        """update_finished sets finished_at timestamp and status."""
        impl = InMemoryLogs()
        run_id = uuid4()
        row = RunLog(
            id=uuid4(),
            merchant_id="merchant_001",
            run_id=run_id,
            pipeline_name="otter_bronze_ingestion",
            status="STARTED",
            started_at=datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC),
            finished_at=None,
            error_class=None,
            error_message=None,
        )
        impl.insert_started(row)
        impl.update_finished(run_id, "SUCCESS", None, None)
        all_rows = impl.get_all()
        assert len(all_rows) == 1
        assert all_rows[0].status == "SUCCESS"
        assert all_rows[0].finished_at is not None

    def test_update_finished_raises_run_not_found_error(self) -> None:
        """update_finished raises RunNotFoundError for unknown run_id."""
        impl = InMemoryLogs()
        unknown_id = uuid4()
        with pytest.raises(RunNotFoundError):
            impl.update_finished(unknown_id, "FAILED", "SomeError", "msg")

    def test_get_all_returns_inserted_rows(self) -> None:
        """get_all returns all rows in insertion order."""
        impl = InMemoryLogs()
        run_id_1 = uuid4()
        run_id_2 = uuid4()
        row1 = RunLog(
            id=uuid4(),
            merchant_id="merchant_001",
            run_id=run_id_1,
            pipeline_name="otter_bronze_ingestion",
            status="STARTED",
            started_at=datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC),
            finished_at=None,
            error_class=None,
            error_message=None,
        )
        row2 = RunLog(
            id=uuid4(),
            merchant_id="merchant_001",
            run_id=run_id_2,
            pipeline_name="otter_bronze_ingestion",
            status="STARTED",
            started_at=datetime(2026, 6, 10, 3, 0, 0, tzinfo=UTC),
            finished_at=None,
            error_class=None,
            error_message=None,
        )
        impl.insert_started(row1)
        impl.insert_started(row2)
        all_rows = impl.get_all()
        assert len(all_rows) == 2
        assert all_rows[0].run_id == run_id_1
        assert all_rows[1].run_id == run_id_2

    def test_protocol_insert_started_signature(self) -> None:
        """LogsPort.Protocol declares insert_started(row: RunLog) -> UUID."""
        import inspect

        sig = inspect.signature(LogsPort.insert_started)
        params = list(sig.parameters.keys())
        assert "row" in params

    def test_protocol_update_finished_signature(self) -> None:
        """LogsPort.Protocol declares update_finished with correct params."""
        import inspect

        sig = inspect.signature(LogsPort.update_finished)
        params = list(sig.parameters.keys())
        assert "run_id" in params
        assert "status" in params
        assert "error_class" in params
        assert "error_message" in params
