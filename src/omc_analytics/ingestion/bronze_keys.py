"""build_bronze_key — pure S3 key builder for Bronze ingestion.

No boto3, no I/O. Returns the S3 key string only.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, timedelta

_VALID_ENDPOINTS = frozenset({"orders", "reports_enqueue", "reports_result"})
_MERCHANT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_logger = logging.getLogger(__name__)


def build_bronze_key(
    merchant_id: str,
    endpoint: str,
    target_date: date,
    run_timestamp_utc: datetime,
) -> str:
    """Build the S3 key for a Bronze ingestion object.

    Format:
        otter/merchant_id={merchant_id}/year=YYYY/month=MM/day=DD/{endpoint}-{YYYYMMDDTHHMMSSZ}.json

    Args:
        merchant_id: Alphanumeric/hyphen/underscore,1-64 chars.
        endpoint: One of "orders", "reports_enqueue", "reports_result".
        target_date: The order/ingestion date used for the Hive partition path.
        run_timestamp_utc: The run timestamp in UTC (used for the filename suffix).

    Returns:
        The S3 key string (not the full URI).

    Raises:
        ValueError: If merchant_id is empty/invalid or endpoint is unknown.
    """
    if not isinstance(target_date, date):
        raise ValueError(f"target_date must be a datetime.date; got: {target_date!r}")
    if not _MERCHANT_ID_RE.match(merchant_id):
        raise ValueError(
            f"merchant_id must be non-empty,1-64 chars, "
            f"matching ^[A-Za-z0-9_-]{{1,64}}$; got: {merchant_id!r}"
        )
    if endpoint not in _VALID_ENDPOINTS:
        raise ValueError(
            f"endpoint must be one of {sorted(_VALID_ENDPOINTS)}; got: {endpoint!r}"
        )

    # Far-future soft warning: >1 day ahead (naive UTC now for portability)
    now_utc_naive = datetime.now(UTC).replace(tzinfo=None)
    if target_date > (now_utc_naive.date() + timedelta(days=1)):
        _logger.warning(
            "target_date %s is more than 1 day in the future; "
            "partition path may be unintended",
            target_date,
        )

    ts = run_timestamp_utc.strftime("%Y%m%dT%H%M%SZ")
    year = str(target_date.year)
    month = f"{target_date.month:02d}"
    day = f"{target_date.day:02d}"

    return (
        f"otter/merchant_id={merchant_id}/"
        f"year={year}/month={month}/day={day}/"
        f"{endpoint}-{ts}.json"
    )
