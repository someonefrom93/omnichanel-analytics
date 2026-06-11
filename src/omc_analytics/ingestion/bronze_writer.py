"""BronzeWriter — S3 adapter for Bronze ingestion layer.

No module-level boto3.client() call — the boto3 client is injected,
which is what enables moto to work in tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from omc_analytics.ingestion.bronze_keys import build_bronze_key
from omc_analytics.ingestion.errors import BronzeWriteError


class BronzeWriter:
    """S3 writer for Bronze ingestion objects.

    Args:
        s3_client: An injected boto3 S3 client (e.g. from moto or real boto3).
        bucket_name: The target S3 bucket name.
    """

    def __init__(self, s3_client: Any, bucket_name: str) -> None:
        self._s3 = s3_client
        self._bucket = bucket_name

    def write_raw(
        self,
        merchant_id: str,
        endpoint: str,
        payload: bytes | str,
        run_timestamp_utc: datetime,
    ) -> str:
        """Write a raw payload to Bronze S3.

        Args:
            merchant_id: Merchant identifier used in the partition path.
            endpoint: One of "orders", "reports_enqueue", "reports_result".
            payload: The raw bytes or string to write.
            run_timestamp_utc: The run timestamp used in the S3 key.

        Returns:
            The full s3://{bucket}/{key} URI.

        Raises:
            BronzeWriteError: If the boto3 put_object call fails.
        """
        key = build_bronze_key(merchant_id, endpoint, run_timestamp_utc)
        try:
            self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=payload if isinstance(payload, bytes) else payload.encode(),
            )
        except ClientError as exc:
            raise BronzeWriteError(
                f"Failed to write s3://{self._bucket}/{key}: {exc}"
            ) from exc
        return f"s3://{self._bucket}/{key}"

    def write_report_pair(
        self,
        merchant_id: str,
        request_body: bytes | str,
        result_payload: bytes | str,
        run_timestamp_utc: datetime,
    ) -> tuple[str, str]:
        """Write both the enqueue manifest and the result payload for a report job.

        Args:
            merchant_id: Merchant identifier.
            request_body: The POST /v1/reports request body (manifest).
            result_payload: The final poll result payload.
            run_timestamp_utc: The run timestamp used in S3 keys.

        Returns:
            A tuple of (manifest_uri, result_uri).
        """
        manifest_uri = self.write_raw(
            merchant_id, "reports_enqueue", request_body, run_timestamp_utc
        )
        result_uri = self.write_raw(
            merchant_id, "reports_result", result_payload, run_timestamp_utc
        )
        return (manifest_uri, result_uri)
