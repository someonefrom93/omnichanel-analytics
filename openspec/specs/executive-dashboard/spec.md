# executive-dashboard Specification

> New capability. Source: umbrella `openspec/changes/streamlit-ui-pr5/proposal.md` — PR5b.

## Purpose

Executive Dashboard page: 3 KPI cards + 3 charts over `fact_financial_sales`, tenant-fenced by
`merchant_id`. Native Streamlit widgets only (`st.metric`, `st.bar_chart`, `st.dataframe`).

## Requirements

### Requirement: Merchant Fence on Dashboard

The dashboard MUST redirect with "Please enter a Merchant ID" if `st.session_state.merchant_id`
is empty. All data queries MUST pass `merchant_id` to `GoldReader` methods.

#### Scenario: Empty merchant blocks dashboard

- GIVEN `st.session_state.merchant_id` is empty
- WHEN dashboard page loads
- THEN page displays warning and stops without loading data

#### Scenario: Valid merchant loads data

- GIVEN `merchant_id="store_001"` and seeded `fact_financial_sales`
- WHEN dashboard loads
- THEN KPI cards and charts render with store_001 data

### Requirement: KPI Cards

The dashboard MUST render 3 `st.metric` cards:
1. **True Net Profit Margin**: `SUM(true_net_payout_margin) / SUM(gross_order_value)` as %
2. **Blended Commission Impact**: `SUM(estimated_marketplace_commission) / SUM(gross_order_value)` as %
3. **Discovered Settlement Variances**: `COUNT(*) WHERE settlement_variance_amount != 0`

#### Scenario: KPIs render with seeded data

- GIVEN 5 fact rows with non-zero values
- WHEN dashboard loads
- THEN all 3 metrics display numeric values > 0

#### Scenario: KPIs handle empty dataset

- GIVEN no rows for merchant
- WHEN dashboard loads
- THEN metrics show "N/A" without crashing

### Requirement: Chart 1 — Profit Leakage Tracker

The dashboard MUST render a grouped horizontal bar chart (`st.bar_chart`) comparing Gross Sales,
Net Payout, and True Profit aggregated by `source_marketplace`.

#### Scenario: Chart renders multi-marketplace data

- GIVEN rows for "UberEats" (3 rows) and "DoorDash" (2 rows)
- WHEN dashboard loads
- THEN chart shows 2 groups with 3 bars each (Gross Sales, Net Payout, True Profit)

#### Scenario: Chart handles single marketplace

- GIVEN rows for only "UberEats"
- WHEN dashboard loads
- THEN chart shows 1 group with 3 bars; no crash

### Requirement: Chart 2 — Menu Engineering Matrix

The dashboard MUST render a sorted horizontal bar chart of Net Profit per `line_item_sku`,
with a target margin baseline line. Sorted descending by net profit.

#### Scenario: Chart sorts by profitability

- GIVEN 4 menu items with varying net profits
- WHEN dashboard loads
- THEN bars sorted highest to lowest net profit

#### Scenario: Chart handles zero/negative profit items

- GIVEN items with net profit <= 0
- WHEN dashboard loads
- THEN bars render at or below baseline without crash

### Requirement: Chart 3 — Payout Reconciliation Audit Log

The dashboard MUST render a `st.dataframe` showing rows where settlement reconciliation
requires review. Columns: `order_id`, `source_marketplace`, `gross_order_value`,
`net_payout_amount`, `settlement_variance_amount`, `variance_reason`.

#### Scenario: Table shows variance rows

- GIVEN 3 rows with non-zero `settlement_variance_amount`
- WHEN dashboard loads
- THEN dataframe displays exactly those 3 rows with variance columns

#### Scenario: Table handles zero variances

- GIVEN all rows have `settlement_variance_amount=0`
- WHEN dashboard loads
- THEN dataframe shows "No variances detected" message
