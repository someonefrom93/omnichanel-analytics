"""Onboarding Wizard — 4-step Streamlit wizard (PR6b).

Step flow: Connect → Callback → Sync → Success.
State machine driven by st.session_state.step (int, 0-3).
"""

from __future__ import annotations

import os

import streamlit as st

# ---------------------------------------------------------------------------
# State init
# ---------------------------------------------------------------------------

if "step" not in st.session_state:
    st.session_state.step = 0

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AUTHORIZE_URL = os.environ.get(
    "OMCAE_OTTER_AUTHORIZE_URL",
    "https://api.otter.dev/oauth/authorize",
)
_REDIRECT_URI = os.environ.get(
    "OMCAE_OAUTH_REDIRECT_URI",
    "http://localhost:8501/onboarding",
)
_CLIENT_ID = os.environ.get("OTTER_CLIENT_ID", "")


# ---------------------------------------------------------------------------
# Step renderers
# ---------------------------------------------------------------------------


def render_step_connect() -> None:
    """Step 0: Connect — show authorize link to Otter."""
    st.title("Connect Your Otter Account")
    st.markdown(
        "To get started, connect your Otter account to OFAE Analytics. "
        "You'll be redirected to Otter to authorize access."
    )

    authorize_url = (
        f"{_AUTHORIZE_URL}"
        f"?response_type=code"
        f"&client_id={_CLIENT_ID}"
        f"&redirect_uri={_REDIRECT_URI}"
        f"&scope=read+reports"
        f"&state=onboarding_{st.session_state.get('merchant_id', 'unknown')}"
    )

    st.markdown(f"[Connect to Otter]({authorize_url})")
    st.caption("After authorizing, you'll be redirected back to complete setup.")


def render_step_callback() -> None:
    """Step 1: Callback — exchange authorization code for tokens."""
    st.title("Completing Connection")
    code = st.query_params.get("code")

    if not code:
        st.warning("No authorization code found. Please go back to step 1.")
        if st.button("← Back to Connect"):
            st.session_state.step = 0
            st.rerun()
        return

    st.info("Authorization code received. Exchanging for tokens...")

    try:
        import requests as _requests

        from omc_analytics.common.secrets import MerchantCredentials
        from omc_analytics.ingestion.oauth import OAuthRefresher

        session = _requests.Session()
        from omc_analytics.common.secrets import InMemorySecrets

        secrets = InMemorySecrets()

        # Bootstrap minimal credentials for the exchange
        creds = MerchantCredentials(
            merchant_id=st.session_state.get("merchant_id", "merchant_001"),
            public_api_url="https://api.otter.dev",  # type: ignore[arg-type]
            client_id=_CLIENT_ID,
            client_secret_encrypted=os.environ.get("OTTER_CLIENT_SECRET", ""),
        )
        secrets.save(creds)

        oauth = OAuthRefresher(session=session, secrets=secrets)
        new_creds = oauth.exchange_authorization_code(
            code=str(code),
            redirect_uri=_REDIRECT_URI,
        )
        secrets.save(new_creds)

        st.success("Connection established! Proceeding to sync...")
        st.session_state.step = 2
        st.rerun()

    except Exception as exc:
        from omc_analytics.common.alerts import InMemoryAlerts
        from omc_analytics.serving.error_banners import (
            classify,
            render_tier1_warning,
            render_tier2_info,
            render_tier3_generic,
        )

        tier = classify(exc)
        if tier == "tier1":
            render_tier1_warning(exc)
        elif tier == "tier2":
            render_tier2_info(exc)
        else:
            alerts = InMemoryAlerts()
            render_tier3_generic(exc, alerts)
        return


def render_step_sync() -> None:
    """Step 2: Sync — run Bronze ingestion in-process."""
    st.title("Syncing Your Data")
    st.info("Running initial Bronze sync. This may take a moment...")

    try:
        from datetime import UTC, datetime
        from uuid import uuid4

        import boto3
        import requests as _requests

        from omc_analytics.common.config import RunContext
        from omc_analytics.common.logs import InMemoryLogs
        from omc_analytics.common.secrets import InMemorySecrets
        from omc_analytics.ingestion.backoff import RetryPolicy
        from omc_analytics.ingestion.bronze_writer import BronzeWriter
        from omc_analytics.ingestion.oauth import OAuthRefresher
        from omc_analytics.ingestion.otter_client import OtterClient
        from omc_analytics.ingestion.run import run_bronze_impl

        merchant_id = st.session_state.get("merchant_id", "merchant_001")
        secrets = InMemorySecrets()
        logs = InMemoryLogs()

        # Build dependencies matching _build_deps pattern
        session = _requests.Session()
        oauth = OAuthRefresher(session=session, secrets=secrets)
        s3_client = boto3.client("s3", region_name="us-east-1")
        bronze = BronzeWriter(
            s3_client=s3_client,
            bucket_name="ofae-data-lakehouse-bronze-dev",
        )

        def clock() -> datetime:
            return datetime.now(UTC)

        rate_policy = RetryPolicy(
            max_retries=3, base_seconds=1.0, cap_seconds=8.0, jitter=True
        )
        trans_policy = RetryPolicy(
            max_retries=1, base_seconds=0.5, cap_seconds=1.0, jitter=True
        )
        poll_policy = RetryPolicy(
            max_retries=10, base_seconds=2.0, cap_seconds=60.0, jitter=True
        )

        otter = OtterClient(
            session=session,
            secrets=secrets,
            oauth_refresher=oauth,
            clock=clock,
            rate_limit_policy=rate_policy,
            transient_401_policy=trans_policy,
            run_id=uuid4(),
        )

        ctx = RunContext(
            run_id=uuid4(),
            merchant_id=merchant_id,
            env="dev",
            bucket_name="ofae-data-lakehouse-bronze-dev",
            run_timestamp_utc=datetime.now(UTC),
            s3_client=s3_client,
            secrets=secrets,
            logs=logs,
            oauth=oauth,
            otter=otter,
            bronze=bronze,
            rate_limit_policy=rate_policy,
            transient_401_policy=trans_policy,
            report_poll_policy=poll_policy,
        )

        run_bronze_impl(ctx)
        st.success("Sync complete!")

        # Display log rows
        all_rows = logs.get_all() if hasattr(logs, "get_all") else []
        if all_rows:
            st.subheader("Sync Log")
            for row in all_rows:
                st.write(f"- {row}")

        # Advance to success step
        st.session_state.step = 3
        st.rerun()

    except Exception as exc:
        from omc_analytics.common.alerts import InMemoryAlerts
        from omc_analytics.serving.error_banners import (
            classify,
            render_tier1_warning,
            render_tier2_info,
            render_tier3_generic,
        )

        tier = classify(exc)
        if tier == "tier1":
            render_tier1_warning(exc)
        elif tier == "tier2":
            render_tier2_info(exc)
        else:
            alerts = InMemoryAlerts()
            render_tier3_generic(exc, alerts)


def render_step_success() -> None:
    """Step 3: Success — green check + link to dashboard."""
    st.title("Setup Complete! 🎉")
    st.success("Your Otter account is connected and your data is synced.")

    st.markdown("### What's next?")
    st.markdown("- View your [Executive Dashboard](/dashboard)")
    st.markdown("- Manage your [COGS Editor](/cogs_editor)")
    st.markdown("- Run additional syncs from the dashboard")

    if st.button("Go to Dashboard"):
        # Navigate to dashboard page
        st.switch_page("pages/dashboard.py")


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

_cur_step = st.session_state.step

if _cur_step == 0:
    render_step_connect()
elif _cur_step == 1:
    render_step_callback()
elif _cur_step == 2:
    render_step_sync()
elif _cur_step == 3:
    render_step_success()
else:
    st.error(f"Unknown step: {_cur_step}")
