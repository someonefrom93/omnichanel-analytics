"""build_bronze_key — pure S3 key builder for Bronze ingestion.

No boto3, no I/O. Returns the S3 key string only.
"""

from __future__ import annotations

import re
from datetime import datetime

_VALID_ENDPOINTS = frozenset({"orders", "reports_enqueue", "reports_result"})
_MERCHANT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def build_bronze_key(
    merchant_id: str, endpoint: str, run_timestamp_utc: datetime
) -> str:
    """Build the S3 key for a Bronze ingestion object.

    Format:
        otter/merchant_id={merchant_id}/year=YYYY/month=MM/day=DD/{endpoint}-{YYYYMMDDTHHMMSSZ}.json

    Args:
        merchant_id: Alphanumeric/hyphen/underscore,1-64 chars.
        endpoint: One of "orders", "reports_enqueue", "reports_result".
        run_timestamp_utc: The run timestamp in UTC.

    Returns:
        The S3 key string (not the full URI).

    Raises:
        ValueError: If merchant_id is empty/invalid or endpoint is unknown.
    """
    if not _MERCHANT_ID_RE.match(merchant_id):
        raise ValueError(
            f"merchant_id must be non-empty,1-64 chars, "
            f"matching ^[A-Za-z0-9_-]{{1,64}}$; got: {merchant_id!r}"
        )
    if endpoint not in _VALID_ENDPOINTS:
        raise ValueError(
            f"endpoint must be one of {sorted(_VALID_ENDPOINTS)}; got: {endpoint!r}"
        )

    ts = run_timestamp_utc.strftime("%Y%m%dT%H%M%SZ")
    date_str = run_timestamp_utc.strftime("%Y/%m/%d")
    year, month, day = date_str.split("/")

    return (
        f"otter/merchant_id={merchant_id}/"
        f"year={year}/month={month}/day={day}/"
        f"{endpoint}-{ts}.json"
    )
