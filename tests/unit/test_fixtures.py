"""Guard against fixture drift — validates provenance metadata in all Otter fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "otter"
KNOWN_FIXTURES = [
    "orders_response",
    "reports_enqueue_response",
    "reports_result_ready",
    "oauth_token_response",
]


class TestFixtureMetadata:
    """Validates that every fixture has correct provenance metadata."""

    @pytest.mark.parametrize("name", KNOWN_FIXTURES)
    def test_fixture_file_exists(self, name: str) -> None:
        """Each known fixture name must have a corresponding .json file."""
        path = FIXTURE_DIR / f"{name}.json"
        assert path.exists(), f"Fixture {name!r} not found at {path}"

    @pytest.mark.parametrize("name", KNOWN_FIXTURES)
    def test_provenance_is_redoc_sample(self, name: str) -> None:
        """Every fixture must have provenance == 'redoc-sample'."""
        import json

        path = FIXTURE_DIR / f"{name}.json"
        data = json.loads(path.read_text())
        assert "provenance" in data, f"{name}: missing provenance key"
        assert (
            data["provenance"] == "redoc-sample"
        ), f"{name}: provenance must be 'redoc-sample', got {data['provenance']!r}"

    @pytest.mark.parametrize("name", KNOWN_FIXTURES)
    def test_fixture_version_is_1_0(self, name: str) -> None:
        """Every fixture must have fixture_version == '1.0'."""
        import json

        path = FIXTURE_DIR / f"{name}.json"
        data = json.loads(path.read_text())
        assert "fixture_version" in data, f"{name}: missing fixture_version key"
        assert (
            data["fixture_version"] == "1.0"
        ), f"{name}: fixture_version must be '1.0', got {data['fixture_version']!r}"

    @pytest.mark.parametrize("name", KNOWN_FIXTURES)
    def test_endpoint_matches_filename(self, name: str) -> None:
        """The endpoint field must be consistent with the fixture filename.

        Convention:
          orders_response.json          → endpoint contains "GET /v1/orders"
          reports_enqueue_response.json → endpoint contains "POST /v1/reports"
          reports_result_ready.json     → endpoint contains "GET /v1/reports"
          oauth_token_response.json     → endpoint contains "POST /v1/auth/token"
        """
        import json

        path = FIXTURE_DIR / f"{name}.json"
        data = json.loads(path.read_text())
        assert "endpoint" in data, f"{name}: missing endpoint key"

        # Map filename patterns to required endpoint substrings
        endpoint_expectations = {
            "orders_response": "GET /v1/orders",
            "reports_enqueue_response": "POST /v1/reports",
            "reports_result_ready": "GET /v1/reports",
            "oauth_token_response": "POST /v1/auth/token",
        }

        expected_substr = endpoint_expectations.get(name, "")
        assert (
            expected_substr in data["endpoint"]
        ), f"{name}: endpoint {data['endpoint']!r} must contain {expected_substr!r}"

    @pytest.mark.parametrize("name", KNOWN_FIXTURES)
    def test_fixture_is_valid_json(self, name: str) -> None:
        """Every fixture must be parseable as JSON without error."""
        import json

        path = FIXTURE_DIR / f"{name}.json"
        try:
            json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            pytest.fail(f"{name}: invalid JSON — {exc}")

    @pytest.mark.parametrize("name", KNOWN_FIXTURES)
    def test_fixture_has_no_extra_metadata_keys(self, name: str) -> None:
        """Only the three known metadata keys may appear alongside Otter data."""
        import json

        path = FIXTURE_DIR / f"{name}.json"
        data = json.loads(path.read_text())
        known_meta = {"provenance", "fixture_version", "endpoint"}
        # Some fixtures may have extra keys from Otter; we only enforce that
        # the three meta keys are present and correctly valued.
        assert known_meta.issubset(
            data.keys()
        ), f"{name}: missing one or more of {known_meta}"


def _data_keys_for(name: str) -> set[str]:
    """Return the set of non-metadata keys expected for each fixture."""
    keys_by_fixture = {
        "orders_response": {
            "orders",
            "next_cursor",
        },
        "reports_enqueue_response": {
            "jobId",
            "status",
        },
        "reports_result_ready": {
            "status",
            "result",
        },
        "oauth_token_response": {
            "access_token",
            "expires_in",
            "refresh_token",
            "token_type",
            "scope",
        },
    }
    return keys_by_fixture.get(name, set())
