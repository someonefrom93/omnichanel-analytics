# Tasks: Executive Dashboard (PR5b)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~320 (200 dashboard + 105 tests + 15 data_access/nav) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr (pre-approved) |
| Chain strategy | not-needed |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: not-needed
400-line budget risk: Low

## Phase 1: Data Layer Foundation

- [x] 1.1 Add `list_fact_financial_sales(*, merchant_id)` to `GoldReader` in `data_access.py`
- [x] 1.2 Add unit test for tenant fence on new method in `tests/unit/serving/test_data_access.py`

## Phase 2: Dashboard Page (pages/dashboard.py)

- [x] 2.1 Merchant fence guard: redirect if `merchant_id` empty, `st.stop()`
- [x] 2.2 KPI section: 3 `st.metric` cards in `st.columns(3)` — True Net Profit Margin, Blended Commission Impact, Settlement Variances
- [x] 2.3 Chart 1 — Profit Leakage Tracker: `st.bar_chart` grouped by `source_marketplace` (Gross Sales vs Net Payout vs True Profit)
- [x] 2.4 Chart 2 — Menu Engineering Matrix: `st.bar_chart` of net profit per `line_item_sku`, sorted descending
- [x] 2.5 Chart 3 — Payout Reconciliation Audit Log: `st.dataframe` filtered to `variance != 0`
- [x] 2.6 Wire navigation: add `st.Page("pages/dashboard.py", title="Executive Dashboard", icon="📊")` to `streamlit_app.py`

## Phase 3: AppTest Scenarios (tests/unit/serving/test_dashboard.py)

- [x] 3.1 Test: dashboard renders all 3 KPI cards with numeric values (seeded 5 rows)
- [x] 3.2 Test: Chart 1 renders multi-marketplace bars (UberEats + DoorDash)
- [x] 3.3 Test: Chart 2 renders sorted menu items by profitability
- [x] 3.4 Test: Chart 3 dataframe shows only variance rows (`settlement_variance_amount != 0`)
- [x] 3.5 Test: empty merchant_id shows warning and stops
- [x] 3.6 Test: tenant isolation — `store_001` dashboard only sees store_001 data
- [x] 3.7 Test: empty dataset (no rows) shows "N/A" on KPIs and info messages on charts
- [x] 3.8 Test: `GoldReader.list_fact_financial_sales` raises `TypeError` without `merchant_id`

## Phase 4: Quality Gates

- [x] 4.1 `uv run ruff check` — zero issues
- [x] 4.2 `uv run mypy src/omc_analytics` — zero issues
- [x] 4.3 `uv run pytest -x` — all tests green
