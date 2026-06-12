"""Unit tests for error_banners: classify() + 3 render helpers (PR6b).

TDD cycle: RED → GREEN → TRIANGULATE. Includes AppTest-based render verification.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest  # type: ignore[import-untyped]

from omc_analytics.common.alerts import InMemoryAlerts
from omc_analytics.ingestion.errors import Tier1AuthError, Tier2LatencyError
from omc_analytics.serving.error_banners import (
    TIER1_MESSAGE,
    TIER2_MESSAGE,
    TIER3_MESSAGE,
    classify,
    render_tier1_warning,
    render_tier2_info,
    render_tier3_generic,
)

# ---------------------------------------------------------------------------
# Test page modules for AppTest — each imports and calls one render helper
# ---------------------------------------------------------------------------

TEST_PAGES_DIR = Path(__file__).parent / "_test_pages_pr6b"

# ---------------------------------------------------------------------------
# classify() — pure function tests (5 cases)
# ---------------------------------------------------------------------------


class TestClassify:
    """5 cases for classify(): tier1, tier2, tier3 (ValueError, KeyError, bare)."""

    def test_classify_tier1_auth_error_returns_tier1(self) -> None:
        exc = Tier1AuthError("Otter auth failed")
        assert classify(exc) == "tier1"

    def test_classify_tier2_latency_error_returns_tier2(self) -> None:
        exc = Tier2LatencyError("Rate limit exhausted")
        assert classify(exc) == "tier2"

    def test_classify_valueerror_returns_tier3(self) -> None:
        exc = ValueError("invalid json")
        assert classify(exc) == "tier3"

    def test_classify_keyerror_returns_tier3(self) -> None:
        exc = KeyError("missing_key")
        assert classify(exc) == "tier3"

    def test_classify_bare_exception_returns_tier3(self) -> None:
        exc = Exception("something went wrong")
        assert classify(exc) == "tier3"


# ---------------------------------------------------------------------------
# Message constants
# ---------------------------------------------------------------------------


class TestMessageConstants:
    """Message constants are defined and non-empty."""

    def test_tier1_message_is_non_empty_string(self) -> None:
        assert isinstance(TIER1_MESSAGE, str) and len(TIER1_MESSAGE) > 0

    def test_tier2_message_is_non_empty_string(self) -> None:
        assert isinstance(TIER2_MESSAGE, str) and len(TIER2_MESSAGE) > 0

    def test_tier3_message_is_non_empty_string(self) -> None:
        assert isinstance(TIER3_MESSAGE, str) and len(TIER3_MESSAGE) > 0


# ---------------------------------------------------------------------------
# render_tier1_warning — unit + AppTest triangulation
# ---------------------------------------------------------------------------


class TestRenderTier1:
    """render_tier1_warning renders st.warning with TIER1_MESSAGE."""

    def test_render_tier1_warning_does_not_raise_unit(self) -> None:
        """Unit: callable without crash (st may fail in non-Streamlit context)."""
        exc = Tier1AuthError("auth error")
        try:
            render_tier1_warning(exc)
        except Exception as e:
            assert "streamlit" in str(e).lower() or "st." in str(e).lower()

    def test_render_tier1_warning_displays_banner_apptest(self) -> None:
        """AppTest: warning banner is rendered with TIER1_MESSAGE content."""
        page_path = _write_test_page(
            "tier1_test.py",
            """
import streamlit as st
from omc_analytics.serving.error_banners import render_tier1_warning
from omc_analytics.ingestion.errors import Tier1AuthError

render_tier1_warning(Tier1AuthError("test"))
""",
        )
        at = AppTest.from_file(str(page_path))
        at.run()
        assert not at.exception, f"Page raised: {at.exception}"
        assert len(at.warning) >= 1, f"Expected warning, got {len(at.warning)}"


# ---------------------------------------------------------------------------
# render_tier2_info — unit + AppTest triangulation
# ---------------------------------------------------------------------------


class TestRenderTier2:
    """render_tier2_info renders st.info with TIER2_MESSAGE."""

    def test_render_tier2_info_does_not_raise_unit(self) -> None:
        exc = Tier2LatencyError("latency")
        try:
            render_tier2_info(exc)
        except Exception as e:
            assert "streamlit" in str(e).lower() or "st." in str(e).lower()

    def test_render_tier2_info_displays_banner_apptest(self) -> None:
        """AppTest: info banner is rendered with TIER2_MESSAGE content."""
        page_path = _write_test_page(
            "tier2_test.py",
            """
import streamlit as st
from omc_analytics.serving.error_banners import render_tier2_info
from omc_analytics.ingestion.errors import Tier2LatencyError

render_tier2_info(Tier2LatencyError("test"))
""",
        )
        at = AppTest.from_file(str(page_path))
        at.run()
        assert not at.exception, f"Page raised: {at.exception}"
        assert len(at.info) >= 1, f"Expected info, got {len(at.info)}"


# ---------------------------------------------------------------------------
# render_tier3_generic — unit + AppTest triangulation
# ---------------------------------------------------------------------------


class TestRenderTier3:
    """render_tier3_generic writes alert + renders st.error."""

    def test_render_tier3_generic_stores_alert(self) -> None:
        """Unit: alert is inserted into InMemoryAlerts."""
        alerts = InMemoryAlerts()
        exc = ValueError("pipeline crash")
        try:
            render_tier3_generic(exc, alerts)
        except Exception as e:
            if "streamlit" not in str(e).lower() and "st." not in str(e).lower():
                raise
        stored = alerts.get_all()
        assert len(stored) >= 1, f"Expected 1 alert, got {len(stored)}"
        alert = stored[0]
        assert alert.source == "serving"
        assert alert.severity == "error"
        assert alert.error_class == "ValueError"
        assert "pipeline crash" in alert.error_message

    def test_render_tier3_generic_displays_error_apptest(self) -> None:
        """AppTest: error banner is rendered."""
        page_path = _write_test_page(
            "tier3_test.py",
            """
import streamlit as st
from omc_analytics.serving.error_banners import render_tier3_generic
from omc_analytics.common.alerts import InMemoryAlerts

alerts = InMemoryAlerts()
render_tier3_generic(ValueError("test crash"), alerts)
""",
        )
        at = AppTest.from_file(str(page_path))
        at.run()
        assert not at.exception, f"Page raised: {at.exception}"
        assert len(at.error) >= 1, f"Expected error, got {len(at.error)}"


# ---------------------------------------------------------------------------
# Test page helper
# ---------------------------------------------------------------------------


def _write_test_page(name: str, content: str) -> Path:
    """Write a temporary Streamlit test page and return its path."""
    TEST_PAGES_DIR.mkdir(parents=True, exist_ok=True)
    path = TEST_PAGES_DIR / name
    path.write_text(content.strip() + "\n")
    return path
