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
# Sidebar — connection-status micro-indicator (PR6a placeholder, full UI in PR6b)
# ---------------------------------------------------------------------------
if "merchant_id" not in st.session_state:
    st.session_state.merchant_id = "merchant_001"

st.sidebar.title("OFAE Analytics")

# Connection status micro-indicator (replace text_input from PR5a)
st.sidebar.markdown(f"🔗 **Connected as:** `{st.session_state.merchant_id}`")

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

onboarding_page = st.Page(  # type: ignore[attr-defined]
    "pages/onboarding.py",
    title="Onboarding",
    icon="🚀",
)

nav = st.navigation(  # type: ignore[attr-defined]
    [onboarding_page, cogs_page, dashboard_page],
    position="sidebar",
)
nav.run()
