# Design: Executive Dashboard (PR5b)

## Technical Approach

Single Streamlit page (`pages/dashboard.py`) with merchant fence from session state,
3 `st.metric` KPI cards via `st.columns(3)`, and 3 chart sections stacked vertically.
All charts use native Streamlit widgets. Data sourced from mock DuckDB in-memory
`fact_financial_sales` view seeded by AppTest. `GoldReader` extended with
`list_fact_financial_sales(merchant_id)` for tenant-fenced reads.

## Architecture Decisions

| # | Decision | Choice | Rejected | Rationale |
|---|----------|--------|----------|-----------|
| 1 | Chart library | Native Streamlit (`st.bar_chart`, `st.dataframe`) | Plotly, Altair | Zero new deps; pre-approved scope; dashboard is directional, not pixel-perfect |
| 2 | Data source (PR5b) | Mock DuckDB in-memory view seeded by AppTest | Real `fact_financial_sales` Gold table | Gold wire-up deferred to PR5c; avoids S3/DuckDB HTTPFS complexity now |
| 3 | Tenant fence | `GoldReader(merchant_id)` argument pattern | Decorator, context manager | Consistent with PR5a; TypeError at call-site if missing |
| 4 | KPI computation | SQL aggregation in `list_fact_financial_sales` | Python-side pandas aggregation | Keep queries simple; DuckDB handles aggregates fast in-memory |
| 5 | Empty-state handling | `st.info("No variances detected")` for zero rows | Silent empty chart | Better UX per spec scenario requirements |

## Data Flow

```
st.session_state.merchant_id
        │
        ▼
dashboard.py — guard: redirect if empty
        │
        ├──► GoldReader(merchant_id).list_fact_financial_sales(merchant_id)
        │         │
        │         ▼ DuckDB SELECT from fact_financial_sales WHERE merchant_id=?
        │         ▼ returns list[dict] with all columns
        │
        ├──► KPI section: compute 3 aggregates from rows
        │    st.columns(3): st.metric("True Net Profit Margin", ...)
        │                   st.metric("Blended Commission Impact", ...)
        │                   st.metric("Settlement Variances", ...)
        │
        ├──► Chart 1: group by source_marketplace, aggregate 3 metrics → st.bar_chart
        ├──► Chart 2: group by line_item_sku, compute net profit → st.bar_chart (sorted)
        └──► Chart 3: filter variance != 0 → st.dataframe
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/omc_analytics/serving/pages/dashboard.py` | Create | Dashboard page: merchant fence, 3 KPI cards, 3 charts |
| `src/omc_analytics/serving/data_access.py` | Modify | +`list_fact_financial_sales(*, merchant_id)` method |
| `src/omc_analytics/serving/streamlit_app.py` | Modify | +dashboard page to `st.navigation` |
| `tests/unit/serving/test_dashboard.py` | Create | AppTest scenarios: KPIs render, charts render, empty states, empty merchant redirect |

## Interfaces

```python
# New on GoldReader
class GoldReader:
    def list_fact_financial_sales(
        self, *, merchant_id: str
    ) -> list[dict[str, Any]]:
        """Return all fact_financial_sales rows for a merchant.
        Columns: order_id, source_marketplace, line_item_sku,
        gross_order_value, net_payout_amount, true_net_payout_margin,
        estimated_marketplace_commission, settlement_variance_amount,
        variance_reason.
        Returns [] if table missing or no rows."""
```

## Mock `fact_financial_sales` Seed Schema

```
Columns:
  merchant_id TEXT,
  order_id TEXT,
  source_marketplace TEXT,
  line_item_sku TEXT,
  gross_order_value DOUBLE,
  net_payout_amount DOUBLE,
  true_net_payout_margin DOUBLE,
  estimated_marketplace_commission DOUBLE,
  settlement_variance_amount DOUBLE,
  variance_reason TEXT
```

Seed rows in AppTest: 5 rows for store_001, 2 for store_002 (tenant isolation test).
At least 1 row with `settlement_variance_amount != 0` and 1 with `= 0`.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `list_fact_financial_sales` tenant fence + TypeError | DuckDB in-memory, seed rows, extend `test_data_access.py` |
| Integration | Dashboard renders KPIs + 3 charts | `AppTest.from_file` via `test_dashboard.py` |
| Integration | Empty merchant redirect | AppTest with empty session state |
| Integration | Tenant isolation (store_001 data only) | AppTest with two merchants seeded |
| Quality | ruff, mypy, black | `uv run ruff check`, `uv run mypy src/omc_analytics`, `uv run black --check .` |

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| `st.bar_chart` DataFrame shape mismatch on single-row groups | Pad with zero columns; test single-marketplace scenario |
| Division by zero on KPI with empty dataset | Guard: if no rows, display "N/A" |
| AppTest state bleed between scenarios | Fresh AppTest session per test; no shared module-level state |
| `streamlit_app.py` navigation missing dashboard page on startup | AppTest asserts both pages in nav |

## Open Questions

None — all decisions locked per pre-approved proposal.
