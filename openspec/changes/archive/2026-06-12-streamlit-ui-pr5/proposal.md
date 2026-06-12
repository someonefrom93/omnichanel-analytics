# Proposal: Streamlit UI (PR5) — COGS Editor + Executive Dashboard

## Intent

Ship the OFAE Streamlit app per PRD §4–§6.3: Recipe Cost editor (writes
a new PostgreSQL `merchant_cogs` table) + executive dashboard (3 KPI
cards + 3 charts reading the Gold star schema). `st.session_state.merchant_id`
MUST fence every read.

## Scope

**PR5a (~380 LOC) — scaffolding + COGS editor:** entry + sidebar `merchant_id` selector (stub auth); `cogs_editor` page with `st.data_editor` + Save → `cogs_writer.upsert`; `GoldReader` Protocol (mandatory `merchant_id` on every method) + `DuckDBGoldReader`; `CogsWriter` Protocol + `PostgresCogsWriter` (mirrors `PostgresLogs`: psycopg2 pool + injected factory) + dev `DuckDBCogsWriter`; `002_create_merchant_cogs.sql` (composite PK); `AppTest` tests.

**PR5b (~320 LOC) — dashboard:** 3 KPI cards (True Net Profit Margin, Blended Commission, Settlement Variances) + 3 charts (Profit Leakage, Menu Engineering, Payout Audit) using `st.bar_chart` / `st.dataframe` only; per-element `AppTest` tests.

**Out of scope:** OAuth, onboarding, Tier 1/2/3 banners, real `merchant_cogs` ref swap, webhooks, cron, WAF.

## Capabilities

**New:** `streamlit-serving` (skeleton, multi-tenant fence, Gold read, COGS write, AppTest) · `executive-dashboard` (3 KPI + 3 charts over `fact_financial_sales` + `dim_menu_catalog` + `merchant_cogs`).
**Modified:** `gold-star-pr4b` — add dbt source for the new PG `merchant_cogs` table (ref switch deferred to PR5c).

## Approach

`pages/` multi-page · DuckDB `read_parquet` (reuses dbt-duckdb) ·
`PostgresLogs` pattern + dev DuckDB stub for COGS · mandatory
`merchant_id` on every `GoldReader` method (type-system fence) · native
`st.bar_chart` + `st.dataframe` (no Plotly/Altair) · split PR5a (~380)
→ PR5b (~320) for the 400-line budget.

## Affected Areas

**PR5a (~380):** NEW `serving/streamlit_app.py` (65), `serving/pages/cogs_editor.py` (95), `serving/data_access.py` (70), `serving/cogs_writer.py` (50), `common/migrations/002_create_merchant_cogs.sql` (15); tests 215; pyproject + docs 25.
**PR5b (~320):** NEW `serving/pages/dashboard.py` (200), test_dashboard_page (105); README (15).

## Risks

- Stub `merchant_id` selector as security footgun (Med) — sidebar enforces; pages redirect if absent.
- DuckDB S3 HTTPFS creds at app start (Med) — lazy-connect; Tier 1/2/3 banner.
- `merchant_cogs` ref switch breaks PR4b tests (Med) — keep seed; add new dbt source; defer ref switch to PR5c.
- Forecast exceeds 400 (High) — split PR5a + PR5b.

## Rollback

`git revert` (additive; no dbt/S3/KMS churn). `DROP TABLE merchant_cogs`
if prod PG has rows. No Gold drop; no S3 cleanup.

## Dependencies

New: `streamlit>=1.32,<2.0`. Existing: dbt-duckdb, psycopg2-binary,
pytest ≥9.0.3. New env var: `OMCAE_COGS_BACKEND` (memory/duckdb/postgres).

## Success Criteria

**PR5a:** `omc-ui` starts on `:8501`; `cogs_editor` lists every SKU and Save persists; missing `merchant_id` on `GoldReader` raises `TypeError`; all 3 backends tested; pytest green.
**PR5b:** dashboard renders 3 KPI + 3 charts over Gold tables; tenant fence holds; under 400 LOC.

## Review Budget

PR5a ~380 · PR5b ~320 · combined ~700 (exceeds 400). **Budget risk: High umbrella, Low per slice.** **Chained PRs: Yes (PR5a → PR5b).** **Decision needed before apply: Yes** — orchestrator surfaces the split per §E.
