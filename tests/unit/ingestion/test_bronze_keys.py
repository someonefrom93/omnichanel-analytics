"""Tests for build_bronze_key pure helper."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

import pytest

from omc_analytics.ingestion.bronze_keys import build_bronze_key


class TestBuildBronzeKeyFormat:
    """Test the S3 key format produced by build_bronze_key."""

    def test_deterministic_format_with_fixed_datetime(self) -> None:
        """Key format is deterministic with a fixed run_timestamp_utc."""
        ts = datetime(2026, 6, 10, 2, 5, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", ts.date(), ts)
        # Format: otter/merchant_id=merchant_001/year=2026/month=06/day=10/orders-20260610T020500Z.json
        assert key == (
            "otter/merchant_id=merchant_001/"
            "year=2026/month=06/day=10/"
            "orders-20260610T020500Z.json"
        )

    def test_key_contains_merchant_id_partition(self) -> None:
        """Key contains the merchant_id Hive partition."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("M999", "orders", ts.date(), ts)
        assert "merchant_id=M999" in key

    def test_key_contains_year_month_day_partitions(self) -> None:
        """Key contains year, month, day Hive partitions."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", ts.date(), ts)
        assert "year=2026" in key
        assert "month=06" in key
        assert "day=10" in key

    def test_endpoint_in_filename(self) -> None:
        """The endpoint name appears in the filename part of the key."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key_orders = build_bronze_key("merchant_001", "orders", ts.date(), ts)
        key_reports_enqueue = build_bronze_key(
            "merchant_001", "reports_enqueue", ts.date(), ts
        )
        key_reports_result = build_bronze_key(
            "merchant_001", "reports_result", ts.date(), ts
        )
        assert key_orders.endswith("orders-20260610T020000Z.json")
        assert key_reports_enqueue.endswith("reports_enqueue-20260610T020000Z.json")
        assert key_reports_result.endswith("reports_result-20260610T020000Z.json")

    def test_timestamp_in_filename_is_run_timestamp(self) -> None:
        """The timestamp in the filename reflects run_timestamp_utc, not wall time."""
        # Fixed run timestamp
        run_ts = datetime(2026, 6, 10, 14, 30, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", run_ts.date(), run_ts)
        # Filename should contain20260610T143000Z
        assert "20260610T143000Z" in key


class TestBuildBronzeKeyMerchantValidation:
    """Test merchant_id input validation."""

    def test_rejects_empty_merchant_id(self) -> None:
        """Empty merchant_id raises ValueError."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="merchant_id"):
            build_bronze_key("", "orders", ts.date(), ts)

    def test_rejects_merchant_id_too_long(self) -> None:
        """merchant_id longer than 64 chars raises ValueError."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        long_id = "a" * 65
        with pytest.raises(ValueError, match="merchant_id"):
            build_bronze_key(long_id, "orders", ts.date(), ts)

    def test_rejects_merchant_id_with_special_chars(self) -> None:
        """merchant_id with non-alphanumeric chars (except _-) raises ValueError."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="merchant_id"):
            build_bronze_key("merchant@001!", "orders", ts.date(), ts)

    def test_accepts_merchant_id_with_underscore_and_hyphen(self) -> None:
        """merchant_id containing _ and - is accepted."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001-test", "orders", ts.date(), ts)
        assert "merchant_id=merchant_001-test" in key

    def test_accepts_64_char_merchant_id(self) -> None:
        """Exactly 64-char merchant_id is accepted."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        valid_id = "A" * 64
        key = build_bronze_key(valid_id, "orders", ts.date(), ts)
        assert valid_id in key


class TestBuildBronzeKeyEndpointValidation:
    """Test endpoint input validation."""

    def test_rejects_unknown_endpoint(self) -> None:
        """Endpoint not in allowed set raises ValueError."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="endpoint"):
            build_bronze_key("merchant_001", "unknown_endpoint", ts.date(), ts)

    def test_accepts_orders_endpoint(self) -> None:
        """orders endpoint is accepted."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", ts.date(), ts)
        assert "orders-" in key

    def test_accepts_reports_enqueue_endpoint(self) -> None:
        """reports_enqueue endpoint is accepted."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "reports_enqueue", ts.date(), ts)
        assert "reports_enqueue-" in key

    def test_accepts_reports_result_endpoint(self) -> None:
        """reports_result endpoint is accepted."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "reports_result", ts.date(), ts)
        assert "reports_result-" in key


class TestBuildBronzeKeyYearMonthDayPadding:
    """Test zero-padding for year/month/day partitions."""

    def test_january_pads_month_to_02(self) -> None:
        """Month1 becomes 01 in partition."""
        ts = datetime(2026, 1, 5, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", ts.date(), ts)
        assert "month=01" in key

    def test_day_5_pads_to_05(self) -> None:
        """Day 5 becomes05 in partition."""
        ts = datetime(2026, 6, 5, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", ts.date(), ts)
        assert "day=05" in key

    def test_double_digit_month_and_day_not_padded(self) -> None:
        """Double-digit month/day appear as-is."""
        ts = datetime(2026, 12, 15, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", ts.date(), ts)
        assert "month=12" in key
        assert "day=15" in key

    def test_key_structure_matches_hive_partitioning(self) -> None:
        """Key follows Hive-style partitioning: key=value/."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", ts.date(), ts)
        # Should match: otter/merchant_id=X/year=YYYY/month=MM/day=DD/filename.json
        pattern = r"^otter/merchant_id=[A-Za-z0-9_-]+/year=\d{4}/month=\d{2}/day=\d{2}/[a-z_]+-\d{8}T\d{6}Z\.json$"
        assert re.match(pattern, key), f"Key does not match expected pattern: {key}"


class TestBuildBronzeKeyTargetDateContract:
    """SCN-014 contract tests: partition from target_date, filename from run_timestamp_utc."""

    def test_partition_path_uses_target_date_not_run_timestamp(self) -> None:
        """Partition year/month/day comes from target_date, not run_timestamp_utc."""
        target_date = date(2026, 5, 1)
        run_ts = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", target_date, run_ts)
        # Partition must reflect target_date (May 1st)
        assert "year=2026" in key
        assert "month=05" in key
        assert "day=01" in key
        # Filename timestamp must reflect run_timestamp_utc (June 10th)
        assert "20260610T120000Z" in key

    def test_same_target_date_different_run_timestamps_share_partition(self) -> None:
        """Two calls with same target_date but different run_timestamp_utc share partition."""
        target_date = date(2026, 6, 9)
        run_ts_a = datetime(2026, 6, 10, 2, 5, 0, tzinfo=UTC)
        run_ts_b = datetime(2026, 6, 10, 14, 30, 0, tzinfo=UTC)
        key_a = build_bronze_key("merchant_001", "orders", target_date, run_ts_a)
        key_b = build_bronze_key("merchant_001", "orders", target_date, run_ts_b)
        # Same partition: strip the filename suffix and compare the partition prefix
        # Key format: otter/merchant_id=X/year=YYYY/month=MM/day=DD/{endpoint}-{ts}.json
        # Partition = everything through day=DD/
        partition_a = "/".join(key_a.split("/")[:5]) + "/"
        partition_b = "/".join(key_b.split("/")[:5]) + "/"
        assert partition_a == partition_b
        # Different filenames
        assert "020500Z" in key_a
        assert "143000Z" in key_b
        assert key_a != key_b

    def test_target_date_in_far_future_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """target_date >1 day in future logs a warning but does not raise."""
        import logging
        from datetime import UTC, timedelta
        from datetime import datetime as _dt

        # Use a run_timestamp_utc anchored to "today" so the future-date check
        # is deterministic regardless of when the test runs.
        now_utc = _dt.now(UTC)
        future_date = (now_utc + timedelta(days=2)).date()
        run_ts = now_utc
        with caplog.at_level(logging.WARNING):
            key = build_bronze_key("merchant_001", "orders", future_date, run_ts)
        # Still produces a valid key
        assert key.startswith("otter/merchant_id=merchant_001/")
        # Warning was logged
        assert any(record.levelno == logging.WARNING for record in caplog.records)
