# Delta for streamlit-serving

> PR5b extends the PR5a baseline. Source: umbrella proposal.

## ADDED Requirements

### Requirement: GoldReader.list_fact_financial_sales

`GoldReader` MUST expose `list_fact_financial_sales(*, merchant_id: str) -> list[dict[str, Any]]`
returning rows from `fact_financial_sales` filtered by `merchant_id`. Missing `merchant_id`
SHALL raise `TypeError`.

#### Scenario: Returns rows scoped to merchant

- GIVEN `fact_financial_sales` seeded with rows for store_001 and store_002
- WHEN `reader.list_fact_financial_sales(merchant_id="store_001")` is called
- THEN only store_001 rows returned

#### Scenario: Empty table returns empty list

- GIVEN `fact_financial_sales` table does not exist in DuckDB
- WHEN method called
- THEN returns `[]` without raising

### Requirement: Dashboard Page Route

`st.navigation` MUST include `pages/dashboard.py` as "Executive Dashboard" page with icon "📊".

#### Scenario: Dashboard available in navigation

- GIVEN the Streamlit app running
- WHEN navigation renders
- THEN "Executive Dashboard" page listed alongside "COGS Editor"

## MODIFIED Requirements

### Requirement: App Entry with Multi-Tenant Fence

The system MUST serve `streamlit_app.py` as entry point with `st.set_page_config(title="OFAE Analytics")`.
Sidebar MUST expose a `merchant_id` text input stored in `st.session_state.merchant_id`
(default `"merchant_001"` for dev; OAuth stub for PR6).
`st.navigation` MUST route to `pages/cogs_editor.py` AND `pages/dashboard.py`.
(Previously: navigation only routed to `pages/cogs_editor.py`.)

#### Scenario: App starts with default merchant

- GIVEN no session state
- WHEN app loads
- THEN sidebar shows "Merchant ID" input with default "merchant_001"
- AND `st.session_state.merchant_id` equals "merchant_001"

#### Scenario: Missing merchant redirects

- GIVEN `st.session_state.merchant_id` is empty string
- WHEN any page renders
- THEN the page MUST display "Please enter a Merchant ID" and not load data
