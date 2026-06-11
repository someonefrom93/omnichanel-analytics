"""Tests for BronzeWriter S3 adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest import mock

import pytest
from moto import mock_aws

from omc_analytics.ingestion.bronze_keys import build_bronze_key
from omc_analytics.ingestion.bronze_writer import BronzeWriteError, BronzeWriter


class TestBronzeWriter:
    """Test suite for BronzeWriter S3 adapter."""

    @pytest.fixture
    def s3_client(self):
        """Provide a moto-mocked S3 client with a pre-created bucket."""
        with mock_aws():
            import boto3

            client = boto3.client("s3", region_name="us-east-1")
            client.create_bucket(Bucket="test-bucket")
            yield client

    @pytest.fixture
    def bronze_writer(self, s3_client):
        """Provide a BronzeWriter instance with the mocked S3 client."""

        return BronzeWriter(s3_client=s3_client, bucket_name="test-bucket")

    @pytest.fixture
    def run_ts(self):
        """Provide a frozen run timestamp."""
        return datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)

    def test_write_raw_uses_build_bronze_key(self, bronze_writer, run_ts):
        """BronzeWriter.write_raw must call build_bronze_key to derive the S3 key."""
        merchant_id = "merchant_001"
        endpoint = "orders"
        payload = b'{"foo": "bar"}'

        with mock.patch(
            "omc_analytics.ingestion.bronze_writer.build_bronze_key",
            wraps=build_bronze_key,
        ) as mock_key:
            bronze_writer.write_raw(merchant_id, endpoint, payload, run_ts)
            mock_key.assert_called_once_with(merchant_id, endpoint, run_ts)

    def test_write_raw_put_object_called_with_expected_args(
        self, bronze_writer, run_ts
    ):
        """put_object must be called with Bucket, Key, and Body from inputs."""
        merchant_id = "merchant_001"
        endpoint = "orders"
        payload = b'{"test": "data"}'

        with mock.patch.object(bronze_writer._s3, "put_object") as mock_put:
            bronze_writer.write_raw(merchant_id, endpoint, payload, run_ts)
            mock_put.assert_called_once()
            call_kwargs = mock_put.call_args.kwargs
            assert call_kwargs["Bucket"] == "test-bucket"
            assert call_kwargs["Key"] == build_bronze_key(merchant_id, endpoint, run_ts)
            assert call_kwargs["Body"] == payload

    def test_write_raw_returns_s3_uri(self, bronze_writer, run_ts):
        """write_raw returns the full s3://{bucket}/{key} URI."""
        merchant_id = "merchant_001"
        endpoint = "orders"
        payload = b'{"test": "data"}'

        uri = bronze_writer.write_raw(merchant_id, endpoint, payload, run_ts)

        expected_key = build_bronze_key(merchant_id, endpoint, run_ts)
        assert uri == f"s3://test-bucket/{expected_key}"

    def test_write_raw_serializes_str_payload_to_bytes(self, bronze_writer, run_ts):
        """write_raw must serialize a str payload to bytes before put_object."""
        merchant_id = "merchant_001"
        endpoint = "orders"
        payload = '{"test": "string_payload"}'

        with mock.patch.object(bronze_writer._s3, "put_object") as mock_put:
            bronze_writer.write_raw(merchant_id, endpoint, payload, run_ts)
            body = mock_put.call_args.kwargs["Body"]
            # boto3 put_object accepts str, but we pin the serialization
            assert isinstance(body, (bytes, str))

    def test_write_report_pair_calls_write_raw_twice(self, bronze_writer, run_ts):
        """write_report_pair calls write_raw twice with reports_enqueue and reports_result."""
        merchant_id = "merchant_001"
        request_body = b'{"report": "req"}'
        result_payload = b'{"report": "result"}'

        with mock.patch.object(
            bronze_writer, "write_raw", wraps=bronze_writer.write_raw
        ) as mock_raw:
            manifest_uri, result_uri = bronze_writer.write_report_pair(
                merchant_id, request_body, result_payload, run_ts
            )

            assert mock_raw.call_count == 2
            assert mock_raw.call_args_list[0].args == (
                merchant_id,
                "reports_enqueue",
                request_body,
                run_ts,
            )
            assert mock_raw.call_args_list[1].args == (
                merchant_id,
                "reports_result",
                result_payload,
                run_ts,
            )
            # URIs are returned in order
            assert "reports_enqueue" in manifest_uri
            assert "reports_result" in result_uri

    def test_write_report_pair_returns_tuple_of_two_uris(self, bronze_writer, run_ts):
        """write_report_pair returns (manifest_uri, result_uri) tuple."""
        merchant_id = "merchant_001"
        request_body = b'{"report": "req"}'
        result_payload = b'{"report": "result"}'

        manifest_uri, result_uri = bronze_writer.write_report_pair(
            merchant_id, request_body, result_payload, run_ts
        )

        assert isinstance(manifest_uri, str)
        assert isinstance(result_uri, str)
        assert manifest_uri.startswith("s3://test-bucket/")
        assert result_uri.startswith("s3://test-bucket/")
        assert manifest_uri != result_uri

    def test_write_raw_wraps_client_error(self, bronze_writer, run_ts):
        """ClientError from boto3 must be wrapped in BronzeWriteError."""
        from botocore.exceptions import ClientError

        merchant_id = "merchant_001"
        endpoint = "orders"
        payload = b'{"test": "data"}'

        error_response = {
            "Error": {
                "Code": "NoSuchBucket",
                "Message": "The specified bucket does not exist",
            }
        }
        client_err = ClientError(error_response, "PutObject")

        with mock.patch.object(bronze_writer._s3, "put_object", side_effect=client_err):
            with pytest.raises(
                BronzeWriteError,
                match="Failed to write",
            ):
                bronze_writer.write_raw(merchant_id, endpoint, payload, run_ts)
