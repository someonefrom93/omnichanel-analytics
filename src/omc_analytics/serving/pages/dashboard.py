"""Executive Dashboard — KPI cards + 3 charts (PR5b).

Reads fact_financial_sales via GoldReader, tenant-fenced by merchant_id
in session state. Uses native Streamlit widgets only.
"""

from __future__ import annotations

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

st.title("Executive Dashboard")
st.caption(f"Metrics for merchant: **{merchant_id}**")

# ---------------------------------------------------------------------------
# Load data via GoldReader
# ---------------------------------------------------------------------------
# Support test injection: if a GoldReader was placed in session state, use it.
# This allows AppTest scenarios to seed data and verify rendering.
if "_gold_reader" in st.session_state:
    reader: GoldReader = st.session_state["_gold_reader"]
else:
    reader = GoldReader(merchant_id=merchant_id)

rows = reader.list_fact_financial_sales(merchant_id=merchant_id)

if not rows:
    st.info("No financial data available for this merchant.")
    st.stop()

df = pd.DataFrame(rows)

# ---------------------------------------------------------------------------
# KPI Cards (3 st.metric in columns)
# ---------------------------------------------------------------------------
gross_total = float(df["gross_order_value"].sum())
net_payout_margin_total = float(df["true_net_payout_margin"].sum())
commission_total = float(df["estimated_marketplace_commission"].sum())
variance_count = int((df["settlement_variance_amount"] != 0).sum())

if gross_total > 0:
    net_margin_pct = round(net_payout_margin_total / gross_total * 100, 1)
    commission_pct = round(commission_total / gross_total * 100, 1)
else:
    net_margin_pct = 0.0
    commission_pct = 0.0

st.subheader("Key Performance Indicators")

col1, col2, col3 = st.columns(3)
col1.metric(
    "True Net Profit Margin",
    f"{net_margin_pct}%",
)
col2.metric(
    "Blended Commission Impact",
    f"{commission_pct}%",
)
col3.metric(
    "Discovered Settlement Variances",
    variance_count,
)

st.divider()

# ---------------------------------------------------------------------------
# Chart 1: Profit Leakage Tracker
# ---------------------------------------------------------------------------
st.subheader("True Omnichannel Profit Leakage Tracker")
st.caption("Gross Sales vs Net Payout vs True Profit by Marketplace")

leakage_df = (
    df.groupby("source_marketplace")
    .agg(
        gross_sales=("gross_order_value", "sum"),
        net_payout=("net_payout_amount", "sum"),
        true_profit=("true_net_payout_margin", "sum"),
    )
    .reset_index()
)

st.bar_chart(
    leakage_df.set_index("source_marketplace"),
)

# ---------------------------------------------------------------------------
# Chart 2: Menu Engineering Matrix
# ---------------------------------------------------------------------------
st.subheader("Menu Engineering Matrix")
st.caption("Net Profit per Menu Item — sorted by profitability")

menu_df = (
    df.groupby("line_item_sku")
    .agg(net_profit=("true_net_payout_margin", "sum"))
    .reset_index()
    .sort_values("net_profit", ascending=False)
)

st.bar_chart(
    menu_df.set_index("line_item_sku"),
)

# ---------------------------------------------------------------------------
# Chart 3: Payout Reconciliation Audit Log
# ---------------------------------------------------------------------------
st.subheader("Payout Reconciliation Audit Log")

variance_df = df[df["settlement_variance_amount"] != 0][
    [
        "order_id",
        "source_marketplace",
        "gross_order_value",
        "net_payout_amount",
        "settlement_variance_amount",
        "variance_reason",
    ]
]

if variance_df.empty:
    st.info("No variances detected — all settlements reconciled.")
else:
    st.dataframe(
        variance_df,
        hide_index=True,
        column_config={
            "order_id": "Order ID",
            "source_marketplace": "Marketplace",
            "gross_order_value": st.column_config.NumberColumn(
                "Gross Sales ($)", format="%.2f"
            ),
            "net_payout_amount": st.column_config.NumberColumn(
                "Net Payout ($)", format="%.2f"
            ),
            "settlement_variance_amount": st.column_config.NumberColumn(
                "Variance ($)", format="%.2f"
            ),
            "variance_reason": "Reason",
        },
    )
