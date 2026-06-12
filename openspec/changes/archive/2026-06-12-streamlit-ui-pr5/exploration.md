# Exploration: streamlit-ui-pr5

> Change key: `streamlit-ui-pr5` — pre-approved name from orchestrator.
> Modes: `hybrid` (OpenSpec + Engram persistence).

## Current State

The OFAE platform's analytical core is shipped (PR1–PR4b). The serving layer
(`src/omc_analytics/serving/`) is **empty** — only an `__init__.py` and a
`__pycache__` dir. The Gold star schema (`fact_financial_sales`,
`dim_menu_catalog`) is materialized in DuckDB, and a `merchant_cogs` dbt seed
exists as a 6-row stub. `PostgresLogs` (in `common/postgres_logs.py`) is the
canonical write-side pattern: psycopg2 `ThreadedConnectionPool` with an
**injected** `connection_factory` callable — it never calls `psycopg2.connect()`
directly. The `pipeline_execution_logs` table DDL lives in
`common/migrations/001_create_pipeline_execution_logs.sql` and is read at
runtime by `SQLiteLogs` to stay schema-synced.

Streamlit itself is **not yet pinned** in `pyproject.toml` — the orchestrator
brief says "Streamlit 1.32.0". We need to add it as a runtime dep. The
config layer (`common/config.py`) already supports a `secrets_backend` /
`logs_backend` factory pattern; PR5 will need a new `serving_backend` (or
similar) env var to choose between in-memory/duckdb stub vs real PostgreSQL
for the COGS table.

`st.session_state.merchant_id` (per PRD §4) is the multi-tenant fence; the
data access layer must inject it into **every** read query. The Gold bucket
path `s3://ofae-data-lakehouse-gold-prod/fact_financial_sales/merchant_id={id}/`
is the canonical S3 prefix — DuckDB reads Parquet via `read_parquet('s3://...')`
in production and `read_parquet('/local/path/...')` in tests (mirroring the
`OMCAE_USE_LOCAL_BRONZE=true` deviation pattern used in `silver_orders.sql`
and `silver_reports.sql`).

`pytest 9.0.3` is the test runner; `streamlit.testing.v1.AppTest` (since
Streamlit 1.28) is the official unit-test API. It does **not** require a
running server — it executes the script in-process and exposes
`at.button[0].click().run()`, `at.dataframe[0]`, `at.exception`, etc.

## Affected Areas

| File / Area | Why it changes |
|---|---|
| `pyproject.toml` | Add `streamlit>=1.32,<2.0` dep; add `streamlit.testing.v1` dev marker; add `[project.scripts] omc-ui = "omc_analytics.serving.streamlit_app:cli"` |
| `src/omc_analytics/serving/__init__.py` | Already empty; no change. |
| `src/omc_analytics/serving/streamlit_app.py` | NEW — `streamlit run` entry point. Sets up page config, sidebar `merchant_id` selector (stub auth), session state, navigation hint. |
| `src/omc_analytics/serving/pages/cogs_editor.py` | NEW (PR5a) — Streamlit page rendering the COGS data editor; calls `cogs_writer.upsert(...)` on Save. |
| `src/omc_analytics/serving/pages/dashboard.py` | NEW (PR5b) — Streamlit page rendering 3 KPI cards + 3 charts. |
| `src/omc_analytics/serving/data_access.py` | NEW — `GoldReader` protocol; `DuckDBGoldReader` impl that reads Parquet from local or S3 (mirrors the `OMCAE_USE_LOCAL_BRONZE` pattern), enforces `merchant_id` filter on every query. |
| `src/omc_analytics/serving/cogs_writer.py` | NEW — `CogsWriter` protocol; `PostgresCogsWriter` impl using the existing `psycopg2.pool.ThreadedConnectionPool` pattern with injected `connection_factory`; `DuckDBCogsWriter` stub for dev. |
| `src/omc_analytics/common/migrations/002_create_merchant_cogs.sql` | NEW — DDL: `merchant_id TEXT, line_item_sku TEXT, recipe_cost NUMERIC, packaging_cost NUMERIC, updated_at TIMESTAMPTZ, PRIMARY KEY (merchant_id, line_item_sku)`. Reuse the `_adapt_postgres_to_sqlite` helper from `sqlite_logs.py` for the dev stub. |
| `src/omc_analytics/common/cogs_migrate.py` | NEW (or fold into `cogs_writer.py`) — apply 002 DDL to the active store on startup (idempotent). |
| `tests/unit/serving/test_data_access.py` | NEW — `GoldReader` isolation contract: every query method **MUST** take `merchant_id` and inject it; test that a missing `merchant_id` raises. |
| `tests/unit/serving/test_cogs_writer.py` | NEW — round-trip upsert against in-memory DuckDB; `PostgresCogsWriter` uses a fake `connection_factory` returning a sqlite-like duckdb connection. |
| `tests/unit/serving/test_cogs_editor_page.py` | NEW (PR5a) — `AppTest.from_file("src/omc_analytics/serving/pages/cogs_editor.py")`, inject a stub `GoldReader` via monkeypatch + `runner.secrets`, assert the data editor renders and the Save button persists. |
| `tests/unit/serving/test_dashboard_page.py` | NEW (PR5b) — `AppTest.from_file("src/omc_analytics/serving/pages/dashboard.py")`; assert 3 KPI cards + 3 chart elements render. |
| `tests/integration/test_serving_e2e.py` | NEW — moto S3 Gold bucket + temp DuckDB + `dbt build` + run the Streamlit app via `AppTest`; assert merchant-isolation holds end-to-end. |
| `README.md` | Document `omc-ui` script, multi-tenant fence, COGS table DDL. |
| `.env.example` | Add `OMCAE_COGS_BACKEND` (memory/duckdb/postgres) + `OMCAE_PG_DSN` (re-used). |

## Approaches

### Fork 1 — Multi-page app structure

| Option | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A. Streamlit `pages/` directory** | `serving/streamlit_app.py` (entry) + `serving/pages/cogs_editor.py` + `serving/pages/dashboard.py` | Native; auto-sidebar nav; AppTest supports `at.switch_page("cogs_editor")` | Page filenames become URL slugs; harder to test individual pages in isolation unless we use `AppTest.from_file` per page | Low |
| **B. `st.navigation` with `st.Page` objects (Streamlit ≥1.36)** | Programmatic registration | Reorder/filter pages in code; testable in isolation | Streamlit 1.32 doesn't have `st.Page` stable; PRD pins 1.32.0; would force a version bump | Med |
| **C. Single-file app with `st.sidebar.radio` for view switch** | One entry, manual nav | Trivial; easy to test as one | Doesn't use Streamlit's idiomatic pattern; scales poorly when PR6 adds more pages | Low |

**Recommendation: A.** Matches the canonical Streamlit multi-page pattern
(per official docs: "Streamlit identifies pages by directory structure and
filenames. Your entrypoint file serves as the app's homepage"). Test each
page with `AppTest.from_file("...pages/cogs_editor.py")` directly — pages
are still runnable as standalone scripts.

### Fork 2 — Gold read-side: DuckDB vs direct Parquet vs S3 Select

| Option | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A. DuckDB `read_parquet()` with HTTPFS for S3** | `duckdb.read_parquet("s3://.../merchant_id={id}/*")` | One query language; matches existing transformation stack; can JOIN Gold + COGS in SQL | Adds DuckDB dep to runtime; S3 creds flow | Low |
| **B. `pyarrow.parquet` + manual partition prune** | List S3 objects, filter on `merchant_id=`, download, concat | No extra runtime dep; explicit control | Reinvents DuckDB's predicate pushdown; slower for non-trivial queries | Med |
| **C. AWS S3 Select** | Server-side SQL | Offloads compute | 1MB / 5GB payload limits; no aggregation; bad fit | Med |

**Recommendation: A.** DuckDB is already a runtime dep (dbt-duckdb
`>=1.8,<2.0`). The `read_parquet` function with S3 HTTPFS gives predicate
pushdown on `merchant_id` and lets us express the 3 charts as 3 SQL queries
(JOIN `fact_financial_sales` + `merchant_cogs`). In dev/test, swap the path
to a local DuckDB file using the `OMCAE_USE_LOCAL_BRONZE` env var (mirrors
the silver layer's existing deviation pattern).

### Fork 3 — COGS write-side: real PostgreSQL now vs DuckDB stub for dev

| Option | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A. Real PostgreSQL in prod, DuckDB stub in dev** (orchestrator's pre-approved) | `CogsWriter` Protocol + `PostgresCogsWriter` (uses the existing psycopg2 + ThreadedConnectionPool + injected factory) + `DuckDBCogsWriter` (in-memory) selected by `OMCAE_COGS_BACKEND` env var | Matches PRD §3.1 "PostgreSQL merchant_cogs"; dev path has zero infra; tests run in-process | Two implementations to maintain; DDL adapter needed for DuckDB | Med |
| **B. PostgreSQL everywhere, even in tests** | Use testcontainers PostgreSQL | Single impl | Already in dev deps (`testcontainers[postgres]>=4.8.0`); slower tests; CI fragility | Low (impl) but **Med-High** CI cost |
| **C. DuckDB everywhere (defer real PG)** | Ship the dev stub only; PR6 does real PG | Faster PR5 | Diverges from PRD §3.1; rollback harder when PR6 needs to add PG | Low now, Med later |

**Recommendation: A.** Mirrors the existing `logs_factory` pattern in
`common/config.py` (memory/sqlite/postgres backends). The PostgresLogs
pattern (psycopg2 `ThreadedConnectionPool` + injected
`connection_factory` + `_acquire()` context manager) is the **exact** pattern
to copy. The dev DuckDB path reuses the
`_adapt_postgres_to_sqlite` helper from `sqlite_logs.py` (PR2a) for DDL
sync. Tests use the DuckDB stub by default (fast, hermetic) and a
handful of integration tests exercise the Postgres path with a mocked
factory.

### Fork 4 — Merchant-tenant fence enforcement

| Option | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A. Mandatory `merchant_id` arg in every `GoldReader` method** | `get_fact_financial_sales(merchant_id, date_range)` — no default value; `TypeError` if missing | Type-checker enforced; testable | Boilerplate | Low |
| **B. `GoldReader` is a **scoped** object: `GoldReader.for_merchant(merchant_id)` returns a bound reader** | `.for_merchant("store_001").get_fact(...)` | Compact call sites; explicit binding | Extra factory step; same total LOC | Low |
| **C. Read `st.session_state.merchant_id` inside the data access layer** | Implicit; no parameter | Shortest call sites | Couples serving layer to Streamlit session state; **untestable** without `AppTest`; can't reuse `data_access` from notebooks/scripts | Low now, **Med** debt |

**Recommendation: A** with a thin **B** wrapper at the page boundary. The
`GoldReader` Protocol is **pure**: it takes `merchant_id` as a mandatory
positional arg on every method. The page function does
`reader = GoldReader.for_merchant(st.session_state.merchant_id)` once, then
calls `reader.get_fact_financial_sales(...)` — and a unit test that calls
`get_fact_financial_sales()` (no merchant_id) fails with `TypeError`. This
makes the multi-tenant fence a **type-system invariant**, not a runtime
convention. Critical for the per-PRD §4 "bulletproof multi-tenant
separation" requirement.

### Fork 5 — Streamlit charting: native `st.bar_chart` vs Plotly vs Altair

| Option | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A. `st.bar_chart` + `st.dataframe` only** (orchestrator's pre-approved) | No new deps; built-in | Simplest; matches the "keep it simple" call | Limited customization; can't add the target margin baseline line for Chart 2 natively (workaround: use `st.dataframe` with a `bar` column) | Low |
| **B. Plotly Express** | `px.bar(orientation='h')` with `add_hline(y=baseline)` | True target-margin baseline; interactive tooltips; matches PRD ASCII mockups | +30MB dep; harder to test via `AppTest` (Plotly renders JSON, not in the widget tree) | Med |
| **C. Altair** | `alt.Chart(...).mark_bar()` + `mark_rule()` for baseline | Declarative; pure-data; testable headlessly | +5MB dep; learning curve | Med |

**Recommendation: A for PR5, B/C deferred to PR6+.** The orchestrator
brief explicitly says "no Plotly/Matplotlib yet — keep it simple." For
Chart 2's target margin baseline, render the data as a `st.dataframe` with
a **styling trick**: add a `cogs_status` column
(`"above_target"`/`"below_target"`) and a `bar` column of bar widths;
`st.dataframe` supports `column_config.BarChartColumn` in Streamlit ≥1.31
which gives the visual baseline for free. If the team wants the real
Plotly baseline, file a PR6 follow-up.

## Recommendation

**Proceed with the proposal as scoped.** All four design forks have
clean choices that mirror prior PRs (multi-page = `pages/` dir; Gold read =
DuckDB `read_parquet`; COGS write = `PostgresLogs` pattern with dev DuckDB
stub; tenant fence = mandatory `merchant_id` arg + type-system invariant).
Charts use native `st.bar_chart` / `st.dataframe` per the orchestrator's
pre-approved decision.

**Split PR5 into PR5a + PR5b per the 400-line Review Workload Guard.** PR5a
ships the COGS editor + Streamlit scaffolding + data access layer + COGS
writer (~340 LOC). PR5b ships the dashboard page + 3 KPI cards + 3 charts
(~280 LOC). Both are autonomously shippable, reversible, and under budget.

The two new capabilities to spec are:

- `streamlit-serving`: the Streamlit app skeleton, multi-tenant fence,
  Gold read access, COGS write access, AppTest testability.
- `executive-dashboard`: the 3 KPI cards + 3 charts consuming
  `fact_financial_sales` and `dim_menu_catalog`.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `st.session_state.merchant_id` stub is a security footgun — easy to forget to set | Med | `streamlit_app.py` sidebar must require merchant_id; page redirects to a "select merchant" view if absent. Document loudly in README + spec. |
| DuckDB `read_parquet` with S3 HTTPFS needs AWS creds at app start | Med | Lazy-connect on first read; show a Tier 1/2/3 error banner per PRD §5.2 if creds are missing. |
| `st.data_editor` for COGS lacks per-row dirty tracking in Streamlit 1.32 | Low | Use `st.data_editor(..., key="cogs_grid", on_change=callback)` + `st.session_state.dirty_rows` set pattern. |
| `merchant_cogs` PostgreSQL DDL drifts from `merchant_cogs_seed.csv` (PR4b) | Med | Single DDL file `common/migrations/002_create_merchant_cogs.sql`; the seed CSV is replaced by a `{{ ref('merchant_cogs') }}` ref in `fact_financial_sales` (PR5c follow-up). Document the seam. |
| Streamlit multi-page `pages/` dir collides with dbt's `dbt_project/models/` test fixtures | Low | `pages/` is under `src/omc_analytics/serving/`, isolated from `dbt_project/`. |
| AppTest runs the page script in a fresh module — sidebar state from `streamlit_app.py` is lost | Low | Each page sets its own `st.session_state.merchant_id` default for tests; use `AppTest.from_file` per page. |
| Forecast ~700-900 LOC exceeds 400-line budget | High | **Split into PR5a + PR5b** (see Recommendation). |

## Ready for Proposal

**Yes.** All five design forks resolved against existing PR1–PR4b patterns
(`PostgresLogs`, `logs_factory`, `OMCAE_USE_LOCAL_BRONZE`, `silver_orders`
deviation). The PR5a/PR5b split mirrors the proven PR4a/PR4b pattern from
the archived pii-gold-pr4 umbrella. The new capabilities
`streamlit-serving` and `executive-dashboard` are the natural cleavage:
PR5a is "data plumbing + write UI", PR5b is "read-only analytics
visualization".
