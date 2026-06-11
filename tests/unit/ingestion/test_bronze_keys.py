"""Tests for build_bronze_key pure helper."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from omc_analytics.ingestion.bronze_keys import build_bronze_key


class TestBuildBronzeKeyFormat:
    """Test the S3 key format produced by build_bronze_key."""

    def test_deterministic_format_with_fixed_datetime(self) -> None:
        """Key format is deterministic with a fixed run_timestamp_utc."""
        ts = datetime(2026, 6, 10, 2, 5, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", ts)
        # Format: otter/merchant_id=merchant_001/year=2026/month=06/day=10/orders-20260610T020500Z.json
        assert key == (
            "otter/merchant_id=merchant_001/"
            "year=2026/month=06/day=10/"
            "orders-20260610T020500Z.json"
        )

    def test_key_contains_merchant_id_partition(self) -> None:
        """Key contains the merchant_id Hive partition."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("M999", "orders", ts)
        assert "merchant_id=M999" in key

    def test_key_contains_year_month_day_partitions(self) -> None:
        """Key contains year, month, day Hive partitions."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", ts)
        assert "year=2026" in key
        assert "month=06" in key
        assert "day=10" in key

    def test_endpoint_in_filename(self) -> None:
        """The endpoint name appears in the filename part of the key."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key_orders = build_bronze_key("merchant_001", "orders", ts)
        key_reports_enqueue = build_bronze_key("merchant_001", "reports_enqueue", ts)
        key_reports_result = build_bronze_key("merchant_001", "reports_result", ts)
        assert key_orders.endswith("orders-20260610T020000Z.json")
        assert key_reports_enqueue.endswith("reports_enqueue-20260610T020000Z.json")
        assert key_reports_result.endswith("reports_result-20260610T020000Z.json")

    def test_timestamp_in_filename_is_run_timestamp(self) -> None:
        """The timestamp in the filename reflects run_timestamp_utc, not wall time."""
        # Fixed run timestamp
        run_ts = datetime(2026, 6, 10, 14, 30, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", run_ts)
        # Filename should contain20260610T143000Z
        assert "20260610T143000Z" in key


class TestBuildBronzeKeyMerchantValidation:
    """Test merchant_id input validation."""

    def test_rejects_empty_merchant_id(self) -> None:
        """Empty merchant_id raises ValueError."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="merchant_id"):
            build_bronze_key("", "orders", ts)

    def test_rejects_merchant_id_too_long(self) -> None:
        """merchant_id longer than 64 chars raises ValueError."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        long_id = "a" * 65
        with pytest.raises(ValueError, match="merchant_id"):
            build_bronze_key(long_id, "orders", ts)

    def test_rejects_merchant_id_with_special_chars(self) -> None:
        """merchant_id with non-alphanumeric chars (except _-) raises ValueError."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="merchant_id"):
            build_bronze_key("merchant@001!", "orders", ts)

    def test_accepts_merchant_id_with_underscore_and_hyphen(self) -> None:
        """merchant_id containing _ and - is accepted."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001-test", "orders", ts)
        assert "merchant_id=merchant_001-test" in key

    def test_accepts_64_char_merchant_id(self) -> None:
        """Exactly 64-char merchant_id is accepted."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        valid_id = "A" * 64
        key = build_bronze_key(valid_id, "orders", ts)
        assert valid_id in key


class TestBuildBronzeKeyEndpointValidation:
    """Test endpoint input validation."""

    def test_rejects_unknown_endpoint(self) -> None:
        """Endpoint not in allowed set raises ValueError."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="endpoint"):
            build_bronze_key("merchant_001", "unknown_endpoint", ts)

    def test_accepts_orders_endpoint(self) -> None:
        """orders endpoint is accepted."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", ts)
        assert "orders-" in key

    def test_accepts_reports_enqueue_endpoint(self) -> None:
        """reports_enqueue endpoint is accepted."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "reports_enqueue", ts)
        assert "reports_enqueue-" in key

    def test_accepts_reports_result_endpoint(self) -> None:
        """reports_result endpoint is accepted."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "reports_result", ts)
        assert "reports_result-" in key


class TestBuildBronzeKeyYearMonthDayPadding:
    """Test zero-padding for year/month/day partitions."""

    def test_january_pads_month_to_02(self) -> None:
        """Month1 becomes 01 in partition."""
        ts = datetime(2026, 1, 5, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", ts)
        assert "month=01" in key

    def test_day_5_pads_to_05(self) -> None:
        """Day 5 becomes05 in partition."""
        ts = datetime(2026, 6, 5, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", ts)
        assert "day=05" in key

    def test_double_digit_month_and_day_not_padded(self) -> None:
        """Double-digit month/day appear as-is."""
        ts = datetime(2026, 12, 15, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", ts)
        assert "month=12" in key
        assert "day=15" in key

    def test_key_structure_matches_hive_partitioning(self) -> None:
        """Key follows Hive-style partitioning: key=value/."""
        ts = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
        key = build_bronze_key("merchant_001", "orders", ts)
        # Should match: otter/merchant_id=X/year=YYYY/month=MM/day=DD/filename.json
        pattern = r"^otter/merchant_id=[A-Za-z0-9_-]+/year=\d{4}/month=\d{2}/day=\d{2}/[a-z_]+-\d{8}T\d{6}Z\.json$"
        assert re.match(pattern, key), f"Key does not match expected pattern: {key}"
