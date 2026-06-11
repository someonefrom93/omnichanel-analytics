"""Tests for pure backfill helpers: compute_window_for_date, compute_backfill_dates.

Strict TDD — all tests written before implementation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

# ---------------------------------------------------------------------------
# compute_window_for_date tests
# ---------------------------------------------------------------------------


def test_window_for_specific_date_in_utc_tz() -> None:
    """Given UTC timezone and date 2026-06-10, when compute_window_for_date is called,
    then start is 2026-06-10T00:00:00+00:00 and end is 2026-06-10T23:59:59.999999+00:00.
    """
    from omc_analytics.ingestion.run import compute_window_for_date

    target_date = date(2026, 6, 10)
    store_tz = ZoneInfo("UTC")

    start_utc, end_utc = compute_window_for_date(target_date, store_tz)

    assert start_utc == datetime(2026, 6, 10, 0, 0, 0, 0, tzinfo=UTC)
    assert end_utc == datetime(2026, 6, 10, 23, 59, 59, 999999, tzinfo=UTC)


def test_window_for_date_in_eastern_tz() -> None:
    """Given America/New_York (UTC-4 in DST, June) and date 2026-06-10,
    when compute_window_for_date is called,
    then start is 2026-06-10T04:00:00+00:00 (midnight EDT in UTC),
    and end is 2026-06-11T03:59:59.999999+00:00 (just before midnight EDT in UTC)."""
    from omc_analytics.ingestion.run import compute_window_for_date

    target_date = date(2026, 6, 10)
    store_tz = ZoneInfo("America/New_York")  # UTC-4 in summer

    start_utc, end_utc = compute_window_for_date(target_date, store_tz)

    # Midnight EDT = 04:00 UTC
    assert start_utc == datetime(2026, 6, 10, 4, 0, 0, 0, tzinfo=UTC)
    # End-of-day EDT 23:59:59.999999 = next day 03:59:59.999999 UTC
    assert end_utc == datetime(2026, 6, 11, 3, 59, 59, 999999, tzinfo=UTC)


def test_window_for_date_in_argentine_tz() -> None:
    """Given America/Argentina/Buenos_Aires (UTC-3, no DST) and date 2026-06-10,
    when compute_window_for_date is called,
    then start is 2026-06-10T03:00:00+00:00 (midnight ART in UTC),
    and end is 2026-06-11T02:59:59.999999+00:00 (just before midnight ART in UTC)."""
    from omc_analytics.ingestion.run import compute_window_for_date

    target_date = date(2026, 6, 10)
    store_tz = ZoneInfo("America/Argentina/Buenos_Aires")  # UTC-3, no DST

    start_utc, end_utc = compute_window_for_date(target_date, store_tz)

    # Midnight ART = 03:00 UTC
    assert start_utc == datetime(2026, 6, 10, 3, 0, 0, 0, tzinfo=UTC)
    # End-of-day ART = next day 02:59:59.999999 UTC
    assert end_utc == datetime(2026, 6, 11, 2, 59, 59, 999999, tzinfo=UTC)


def test_window_for_date_in_dst_transition() -> None:
    """Given DST fall-back boundary in America/New_York (2026-11-01),
    when compute_window_for_date is called for 2026-11-01,
    then the window correctly spans all 24 hours of that calendar date.

    On 2026-11-01 in New York, clocks fall back from 02:00 EDT to 01:00 EST.
    Nov 1st starts in EDT (UTC-4) at 00:00 local.
    The window from 00:00 local to 23:59:59.999999 local covers the full day.
    In UTC that is:
      - start: 2026-11-01 00:00 EDT = 2026-11-01 04:00 UTC
      - end:   2026-11-01 23:59:59.999999 EST = 2026-11-02 04:59:59.999999 UTC
    """
    from omc_analytics.ingestion.run import compute_window_for_date

    target_date = date(2026, 11, 1)
    store_tz = ZoneInfo("America/New_York")

    start_utc, end_utc = compute_window_for_date(target_date, store_tz)

    # Start: 2026-11-01 00:00 EDT = 2026-11-01 04:00 UTC
    assert start_utc == datetime(2026, 11, 1, 4, 0, 0, 0, tzinfo=UTC)
    # End: 2026-11-01 23:59:59.999999 EST = 2026-11-02 04:59:59.999999 UTC
    assert end_utc == datetime(2026, 11, 2, 4, 59, 59, 999999, tzinfo=UTC)


# ---------------------------------------------------------------------------
# compute_t1_window regression test
# ---------------------------------------------------------------------------


def test_t1_window_behavior_unchanged_after_refactor() -> None:
    """After refactoring, compute_t1_window must produce identical output to
    compute_window_for_date((now_utc - timedelta(days=1)).date(), store_tz).

    Test case: now_utc=2026-06-11T12:00:00Z, store_tz=America/Bogota (UTC-5).
    T-1 in Bogota is 2026-06-09 (yesterday local is 2026-06-10, so T-1 is 2026-06-09).
    Expected: start=2026-06-09T05:00:00Z, end=2026-06-10T04:59:59.999999Z.
    """
    from omc_analytics.ingestion.run import compute_t1_window, compute_window_for_date

    store_tz = ZoneInfo("America/Bogota")
    now_utc = datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)

    start, end = compute_t1_window(store_tz, now_utc)

    # Compute expected via compute_window_for_date (the new pure path)
    yesterday = (now_utc - timedelta(days=1)).date()
    expected_start, expected_end = compute_window_for_date(yesterday, store_tz)

    assert start == expected_start
    assert end == expected_end


# ---------------------------------------------------------------------------
# compute_backfill_dates tests
# ---------------------------------------------------------------------------


def test_backfill_dates_default_30_days_ends_yesterday() -> None:
    """Given days=30 and now_utc=2026-06-10T12:00:00Z,
    when compute_backfill_dates is called,
    then returns 30 dates from 2026-05-11 to 2026-06-09 (yesterday, 30 days back).

    Formula: [(now_utc.date() - timedelta(days=i)) for i in range(days, 0, -1)]
    """
    from omc_analytics.ingestion.run import compute_backfill_dates

    days = 30
    now_utc = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)

    result = compute_backfill_dates(days, now_utc)

    assert len(result) == 30
    assert result[0] == date(2026, 5, 11)  # now - 30 days
    assert result[-1] == date(2026, 6, 9)  # yesterday
    # Verify ordering: oldest-first
    assert result == sorted(result)


def test_backfill_dates_custom_5_days() -> None:
    """Given days=5 and now_utc=2026-06-10T12:00:00Z,
    when compute_backfill_dates is called,
    then returns 5 dates from 2026-06-05 to 2026-06-09."""
    from omc_analytics.ingestion.run import compute_backfill_dates

    days = 5
    now_utc = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)

    result = compute_backfill_dates(days, now_utc)

    assert len(result) == 5
    assert result[0] == date(2026, 6, 5)
    assert result[-1] == date(2026, 6, 9)


def test_backfill_dates_rejects_days_below_min() -> None:
    """Given days=0 and now_utc=2026-06-11T12:00:00Z,
    when compute_backfill_dates is called,
    then raises ValueError with a message containing '1' and '90'."""
    from omc_analytics.ingestion.run import compute_backfill_dates

    days = 0
    now_utc = datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)

    with pytest.raises(ValueError) as exc_info:
        compute_backfill_dates(days, now_utc)

    assert "1" in str(exc_info.value)
    assert "90" in str(exc_info.value)


def test_backfill_dates_rejects_days_above_max() -> None:
    """Given days=91 and now_utc=2026-06-11T12:00:00Z,
    when compute_backfill_dates is called,
    then raises ValueError with a message containing '1' and '90'."""
    from omc_analytics.ingestion.run import compute_backfill_dates

    days = 91
    now_utc = datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)

    with pytest.raises(ValueError) as exc_info:
        compute_backfill_dates(days, now_utc)

    assert "1" in str(exc_info.value)
    assert "90" in str(exc_info.value)


def test_backfill_dates_rejects_negative() -> None:
    """Given days=-1 and now_utc=2026-06-11T12:00:00Z,
    when compute_backfill_dates is called,
    then raises ValueError (negative is below the min of 1)."""
    from omc_analytics.ingestion.run import compute_backfill_dates

    days = -1
    now_utc = datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)

    with pytest.raises(ValueError):
        compute_backfill_dates(days, now_utc)
