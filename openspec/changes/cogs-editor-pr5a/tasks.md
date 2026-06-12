# Tasks: COGS Editor + Streamlit Scaffolding (PR5a)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~380 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Delivery strategy | single-pr |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

## Phase 1: Foundation

- [ ] 1.1 Add `streamlit>=1.32.0` to `pyproject.toml` runtime deps; add mypy override for streamlit

## Phase 2: Data Layer

- [ ] 2.1 Create `src/omc_analytics/common/migrations/002_create_merchant_cogs.sql` (idempotent DDL: id UUID PK, merchant_id, line_item_sku, recipe_cost, packaging_cost, updated_at, UNIQUE constraint)
- [ ] 2.2 Create `tests/unit/serving/test_migration_002_ddl.py` — tests DDL idempotency via SQLite adapter (mirrors existing test_migration_ddl.py pattern)

## Phase 3: Write Adapter

- [ ] 3.1 Create `src/omc_analytics/serving/cogs_writer.py` — `CogsWriter(connection_factory)` with upsert/delete, psycopg2 ThreadedConnectionPool + _acquire context manager
- [ ] 3.2 Create `tests/unit/serving/test_cogs_writer.py` — test upsert insert, upsert update, delete, pool acquire/release

## Phase 4: Read Adapter

- [ ] 4.1 Create `src/omc_analytics/serving/data_access.py` — `GoldReader(merchant_id)` with list_menu_items, list_merchant_cogs via DuckDB; mandatory merchant_id TypeError guard
- [ ] 4.2 Create `tests/unit/serving/test_data_access.py` — test tenant fence (missing merchant_id raises TypeError), test merchant scoping

## Phase 5: Streamlit UI

- [ ] 5.1 Create `src/omc_analytics/serving/streamlit_app.py` — entry with `st.set_page_config`, sidebar merchant_id text_input defaulting to "merchant_001", `st.navigation` routing to cogs_editor
- [ ] 5.2 Create `src/omc_analytics/serving/pages/__init__.py`
- [ ] 5.3 Create `src/omc_analytics/serving/pages/cogs_editor.py` — `st.data_editor` with editable recipe_cost/packaging_cost + Save button → CogsWriter.upsert; empty merchant redirect
- [ ] 5.4 Create `tests/unit/serving/test_streamlit_app.py` — AppTest scenarios: full editor flow (load→edit→Save), merchant fence (empty merchant_id shows "Please enter a Merchant ID")
