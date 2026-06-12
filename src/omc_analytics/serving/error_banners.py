"""Error banner classification and rendering for Streamlit pages (PR6b).

Pure `classify(exc)` maps exceptions to Tier 1/2/3.
Three render helpers display the correct banner + alert write for Tier 3.
"""

from __future__ import annotations

import traceback
from datetime import UTC, datetime
from uuid import uuid4

import streamlit as st

from omc_analytics.common.alerts import AlertsPort, EngineeringAlert
from omc_analytics.ingestion.errors import Tier1AuthError, Tier2LatencyError

# ---------------------------------------------------------------------------
# Message constants
# ---------------------------------------------------------------------------

TIER3_MESSAGE = (
    "Something went wrong during the onboarding process. "
    "Our engineering team has been notified and will investigate. "
    "Please try again later or contact support."
)

TIER1_MESSAGE = (
    "⚠️ **Connection Issue**: We couldn't connect to your Otter account. "
    "Please check your Otter credentials and try again. "
    "If the problem persists, verify your Otter account is active."
)

TIER2_MESSAGE = (
    "ℹ️ **Temporary Delay**: Otter's servers are experiencing high load. "
    "Your data is still being processed. "
    "This page will update automatically when the sync completes."
)


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


def classify(exc: Exception) -> str:
    """Classify an exception into a Tier string.

    Args:
        exc: The exception to classify.

    Returns:
        "tier1" for auth errors, "tier2" for latency errors,
        "tier3" for everything else (defensive fallback).
    """
    try:
        if isinstance(exc, Tier1AuthError):
            return "tier1"
        if isinstance(exc, Tier2LatencyError):
            return "tier2"
        return "tier3"
    except Exception:
        return "tier3"


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def render_tier1_warning(exc: Exception) -> None:
    """Display a warning banner for Tier 1 (auth) errors.

    Args:
        exc: The Tier1AuthError to render.
    """
    st.warning(TIER1_MESSAGE)


def render_tier2_info(exc: Exception) -> None:
    """Display an info banner for Tier 2 (latency) errors.

    Args:
        exc: The Tier2LatencyError to render.
    """
    st.info(TIER2_MESSAGE)


def render_tier3_generic(exc: Exception, alerts: AlertsPort) -> None:
    """Display a generic error banner and write an engineering alert.

    Args:
        exc: The exception that triggered Tier 3.
        alerts: An AlertsPort implementation for persisting the alert.
    """
    st.error(TIER3_MESSAGE)

    # Best-effort alert write — never raise if alert insertion fails
    try:
        alert = EngineeringAlert(
            id=uuid4(),
            source="serving",
            severity="error",
            error_class=type(exc).__name__,
            error_message=str(exc)[:1000],
            stack_trace=traceback.format_exc()[:5000],
            created_at=datetime.now(UTC),
        )
        alerts.insert_alert(alert)
    except Exception:
        pass
