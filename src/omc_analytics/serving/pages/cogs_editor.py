"""COGS Editor — Streamlit page for editing recipe and packaging costs.

Uses st.data_editor for in-place editing of menu item costs.
Save button persists changes via CogsWriter.upsert.
Requires merchant_id in st.session_state.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from omc_analytics.serving.data_access import GoldReader

# ---------------------------------------------------------------------------
# Guard: merchant_id must be present in session state
# ---------------------------------------------------------------------------
merchant_id: str
if "merchant_id" in st.session_state:
    merchant_id = str(st.session_state.merchant_id).strip()
else:
    merchant_id = ""

if not merchant_id:
    st.warning("Please enter a Merchant ID in the sidebar to continue.")
    st.stop()

st.title("COGS Editor")
st.caption(f"Editing costs for merchant: **{merchant_id}**")

# ---------------------------------------------------------------------------
# Load data via GoldReader
# ---------------------------------------------------------------------------
reader = GoldReader(merchant_id=merchant_id)

# For dev: use in-memory DuckDB with sample data fallback
menu_items = reader.list_menu_items(merchant_id=merchant_id)

if not menu_items:
    st.info("No menu items found. Loading sample data for development.")
    sample_data = [
        {"line_item_sku": "BURGER_CLASSIC", "line_item_name": "Classic Burger"},
        {"line_item_sku": "FRIES_MEDIUM", "line_item_name": "Medium Fries"},
        {"line_item_sku": "COLA_LARGE", "line_item_name": "Large Cola"},
    ]
    # Seed sample COGS data if not present
    cogs_data = reader.list_merchant_cogs(merchant_id=merchant_id)
    from omc_analytics.serving.cogs_writer import CogsWriter

    cogs_dsn = os.environ.get("OMCAE_COGS_DSN", "")
    if cogs_dsn:
        writer = CogsWriter(dsn=cogs_dsn)
    menu_items = sample_data

# ---------------------------------------------------------------------------
# Build the editable dataframe
# ---------------------------------------------------------------------------

df = pd.DataFrame(menu_items)

# Ensure cost columns exist with defaults
if "recipe_cost" not in df.columns:
    df["recipe_cost"] = 0.0
if "packaging_cost" not in df.columns:
    df["packaging_cost"] = 0.0

# Configure column editing — only cost columns are editable
column_config = {
    "line_item_sku": st.column_config.TextColumn("SKU", disabled=True),
    "line_item_name": st.column_config.TextColumn("Item Name", disabled=True),
    "recipe_cost": st.column_config.NumberColumn(
        "Recipe Cost ($)",
        min_value=0.0,
        step=0.01,
        format="%.2f",
    ),
    "packaging_cost": st.column_config.NumberColumn(
        "Packaging Cost ($)",
        min_value=0.0,
        step=0.01,
        format="%.2f",
    ),
}

edited_df = st.data_editor(
    df,
    column_config=column_config,
    width="stretch",
    hide_index=True,
    num_rows="fixed",
    key="cogs_editor_grid",
)  # type: ignore[call-overload]

# ---------------------------------------------------------------------------
# Save button
# ---------------------------------------------------------------------------
if st.button("💾 Save Changes", type="primary"):
    cogs_dsn = os.environ.get("OMCAE_COGS_DSN", "")
    if not cogs_dsn:
        st.success(
            f"Changes saved (dev mode — no database). "
            f"{len(edited_df)} rows processed."
        )
        st.balloons()
    else:
        from omc_analytics.serving.cogs_writer import CogsWriter

        writer = CogsWriter(dsn=cogs_dsn)
        saved = 0
        for _, row in edited_df.iterrows():
            writer.upsert(
                merchant_id=merchant_id,
                line_item_sku=row["line_item_sku"],
                recipe_cost=float(row.get("recipe_cost", 0)),
                packaging_cost=float(row.get("packaging_cost", 0)),
            )
            saved += 1
        st.success(f"✅ Saved {saved} items to merchant_cogs.")
        st.balloons()
