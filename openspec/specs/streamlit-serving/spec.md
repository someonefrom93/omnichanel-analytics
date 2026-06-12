# streamlit-serving Specification

> Source: umbrella `openspec/changes/streamlit-ui-pr5/proposal.md` — PR5a + PR5b.

## Purpose

Streamlit app scaffolding with multi-tenant fence (`merchant_id` in session state),
COGS editor page (data grid + upsert), executive dashboard (3 KPI cards + 3 charts),
and read/write adapters for Gold data layer.
PR5a delivered entry, sidebar, COGS editor, and data access; PR5b added dashboard and `list_fact_financial_sales`.

## Requirements

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

### Requirement: merchant_cogs DDL

The system MUST provide migration `002_create_merchant_cogs.sql` creating table
`merchant_cogs (id UUID PK, merchant_id TEXT NOT NULL, line_item_sku TEXT NOT NULL,
recipe_cost DECIMAL NOT NULL, packaging_cost DECIMAL NOT NULL, updated_at TIMESTAMPTZ NOT NULL)`.
Migration MUST be idempotent (`IF NOT EXISTS`). Composite unique index on
`(merchant_id, line_item_sku)`.

#### Scenario: Table created idempotently

- GIVEN migration 001 applied
- WHEN `002_create_merchant_cogs.sql` runs
- THEN `merchant_cogs` exists with correct schema
- WHEN run again, no error

### Requirement: GoldReader with Mandatory merchant_id

`GoldReader` class MUST accept `merchant_id: str` in constructor.
Every read method MUST require `merchant_id` as parameter.
Methods: `list_menu_items()`, `list_merchant_cogs()`, `list_fact_financial_sales()`.
Missing `merchant_id` on any method SHALL raise `TypeError`.

#### Scenario: GoldReader enforces tenant fence

- GIVEN GoldReader instantiated with `merchant_id="store_001"`
- WHEN calling `reader.list_menu_items()` without `merchant_id` arg
- THEN `TypeError` is raised

#### Scenario: GoldReader lists menu items scoped to merchant

- GIVEN GoldReader connected to DuckDB with `dim_menu_catalog` rows for store_001 and store_002
- WHEN `reader.list_menu_items(merchant_id="store_001")` is called
- THEN only store_001 rows are returned

#### Scenario: list_fact_financial_sales scoped to merchant

- GIVEN `fact_financial_sales` seeded with rows for store_001 and store_002
- WHEN `reader.list_fact_financial_sales(merchant_id="store_001")` is called
- THEN only store_001 rows returned

#### Scenario: list_fact_financial_sales empty table

- GIVEN `fact_financial_sales` table does not exist in DuckDB
- WHEN method called
- THEN returns `[]` without raising

### Requirement: CogsWriter with Upsert/Delete

`CogsWriter` class SHALL accept `connection_factory` (mirroring `PostgresLogs`).
Methods: `upsert(merchant_id, line_item_sku, recipe_cost, packaging_cost)` using
`INSERT ... ON CONFLICT (merchant_id, line_item_sku) DO UPDATE`;
`delete(merchant_id, line_item_sku)`. All operations MUST use psycopg2
`ThreadedConnectionPool` with `_acquire` context manager.

#### Scenario: Upsert inserts new row

- GIVEN empty `merchant_cogs` table
- WHEN `writer.upsert("store_001", "BURGER", 3.50, 0.80)` called
- THEN row exists with `recipe_cost=3.50, packaging_cost=0.80`

#### Scenario: Upsert updates existing row

- GIVEN existing row for ("store_001", "BURGER") with recipe_cost=3.50
- WHEN `writer.upsert("store_001", "BURGER", 4.20, 0.90)` called
- THEN row updated to `recipe_cost=4.20, packaging_cost=0.90`

### Requirement: COGS Editor Page

Page at `pages/cogs_editor.py` MUST render `st.data_editor` over menu items with
editable `recipe_cost`, `packaging_cost` columns. "Save Changes" button MUST
call `CogsWriter.upsert` per modified row. Page MUST redirect user if
`merchant_id` is missing from session state.

#### Scenario: Editor loads and saves

- GIVEN `merchant_id="store_001"`, 3 menu items in GoldReader
- WHEN COGS editor page loads
- THEN `st.data_editor` shows 3 rows with editable cost columns
- WHEN user edits row 1 costs and clicks "Save Changes"
- THEN `CogsWriter.upsert` called for modified row with new values

#### Scenario: Empty merchant blocks editor

- GIVEN `st.session_state.merchant_id` is empty
- WHEN COGS editor page loads
- THEN page shows "Please enter a Merchant ID" and no data grid

### Requirement: Dashboard Page Route

`st.navigation` MUST include `pages/dashboard.py` as "Executive Dashboard" page with icon "📊".

#### Scenario: Dashboard available in navigation

- GIVEN the Streamlit app running
- WHEN navigation renders
- THEN "Executive Dashboard" page listed alongside "COGS Editor"

### Requirement: AppTest Scenarios

Integration test `test_cogs_editor` MUST use `AppTest.from_file` with real Streamlit
session, run through: load → verify data grid → edit cell → click Save → verify
`CogsWriter.upsert` called. `test_sidebar_merchant_fence` MUST assert
default merchant and empty-merchant redirect.

#### Scenario: AppTest simulates full editor flow

- GIVEN AppTest session pointed at COGS editor page with seeded DuckDB
- WHEN simulating page load, cell edit, and Save button click
- THEN session displays 3 rows, update passes, no exception

#### Scenario: AppTest validates merchant fence

- GIVEN AppTest session with empty merchant_id
- WHEN cogs editor page loads
- THEN page text contains "Please enter a Merchant ID"
