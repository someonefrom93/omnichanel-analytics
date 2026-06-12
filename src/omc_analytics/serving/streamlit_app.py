"""Streamlit entry point for the OFAE Analytics app.

Multi-tenant fence: sidebar merchant_id stored in st.session_state.
Pages auto-discovered via st.navigation from the pages/ directory.
"""

from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Page configuration (MUST be the first st. call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="OFAE Analytics",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar — merchant_id selector (stub for PR6 OAuth)
# ---------------------------------------------------------------------------
if "merchant_id" not in st.session_state:
    st.session_state.merchant_id = "merchant_001"

st.sidebar.title("OFAE Analytics")

st.session_state.merchant_id = st.sidebar.text_input(
    "Merchant ID",
    value=st.session_state.merchant_id,
    help="Enter the merchant ID to view data. Default: merchant_001 (dev).",
)

# ---------------------------------------------------------------------------
# Page routing via st.navigation
# ---------------------------------------------------------------------------
cogs_page = st.Page(  # type: ignore[attr-defined]
    "pages/cogs_editor.py",
    title="COGS Editor",
    icon="💰",
)

dashboard_page = st.Page(  # type: ignore[attr-defined]
    "pages/dashboard.py",
    title="Executive Dashboard",
    icon="📊",
)

nav = st.navigation(  # type: ignore[attr-defined]
    [cogs_page, dashboard_page],
    position="sidebar",
)
nav.run()
