# Proposal: Silver Transformation (PR3) — dbt + dbt-duckdb

> **Umbrella**: `silver-transformation-pr3`. **Recommended split**: PR3a (dbt setup + `silver_orders`) + PR3b (`silver_reports` + e2e polish).
> **Date**: 2026-06-11 · **Forecast (gross)**: ~600 LOC combined · **Budget risk**: High
> **Decision needed before apply**: Yes — chain into PR3a/PR3b per Review Workload Guard §E.
> **Chained PRs recommended**: Yes.
> **400-line budget risk**: High (gross forecast > 400).
> **Delivery strategy on PR3 umbrella**: `ask-on-risk` — orchestrator surfaces split to user; user confirms.

## Intent

Stand up the Silver tier of the OFAE medallion (PRD §3) by reading the existing Bronze S3 raw JSON written by PR1/PR2a/PR2b and materializing two conformed/flattened Parquet tables via **dbt-core + dbt-duckdb** (PRD §3.1). This is the first transformation layer and unlocks the Gold star-schema (PR4+) and the Streamlit dashboard (PR5). Per PRD §5.3, every Silver model MUST ship with dbt tests covering `not_null` and composite/scalar `unique` constraints.

The umbrella is over the 400-line review budget, so the proposal explicitly recommends a **chained split (PR3a + PR3b)**. The final decision is left to the orchestrator + user (per the `ask-on-risk` delivery strategy).

## Scope

### In Scope (PR3 umbrella — both PR3a and PR3b combined)

1. **dbt toolchain install** — `dbt-core>=1.8,<2.0` and `dbt-duckdb>=1.8,<2.0` added to `pyproject.toml` runtime deps. Pin DuckDB to the version dbt-duckdb vendors.
2. **dbt project layout** — `dbt_project/` with `dbt_project.yml`, `profiles.yml` (templated, env-driven), `models/silver/`, `macros/`, `tests/`, `packages.yml` (no external packages in PR3).
3. **DuckDB profile with `httpfs` S3 access** — `extensions: [httpfs, parquet]`; `secrets:` block reads `OMCAE_S3_*` env vars; `scope:` restricts credentials to the Bronze bucket prefix. Production default = **S3-direct read via httpfs**; dev/test override = **local mirror** (path swap in profile via target selection).
4. **Bronze source definitions** — two dbt sources:
   - `bronze.orders` — `external_location: "read_json_auto('s3://ofae-data-lakehouse-bronze-{env}/otter/merchant_id=*/*/*/*/orders-*.json', format='array')"` (PR1 writes one JSON file per run; the Otter API returns an array of orders, so `format='array'` is the correct read mode).
   - `bronze.reports_enqueue` and `bronze.reports_result` — two `external_location` sources keyed by their respective `reports_*` filename patterns. Joined downstream by `run_timestamp_utc` extracted from the filename suffix.
5. **Silver model `silver_orders`** (PR3a) — flattens one row per **line item** from the nested Otter orders JSON. Columns: `order_id`, `source_marketplace` (from `channel`), `merchant_id`, `created_at`, `total_amount` (BIGINT, smallest currency unit per Otter API), `total_currency`, `line_item_sku`, `line_item_name`, `line_item_qty`, `line_item_unit_price`, `line_item_unit_currency`, `customer_name_hash` (raw, copied from `customer.name_hash` — **NOT salted**, PII deferral to PR4), `customer_phone_hash` (raw, copy only). Materialization: `incremental`, `incremental_strategy='merge'`, `unique_key=['order_id', 'source_marketplace']` (composite per PRD §5.3).
6. **Silver model `silver_reports`** (PR3b) — joins Bronze `reports_enqueue` and `reports_result` by the partition run timestamp (extracted via DuckDB `regexp_extract(filename, 'reports_.*-(\d{8}T\d{6}Z)\.json', 1)`) OR by `target_date` (parsed from partition path). One row per report job. Columns: `job_id`, `merchant_id`, `report_date`, `enqueue_at`, `result_status`, `result_period_start`, `result_period_end`, `gross_sales_amount`, `gross_sales_currency`, `net_payout_amount`, `net_payout_currency`. Materialization: `incremental`, `unique_key='job_id'`.
7. **dbt tests** (per PRD §5.3):
   - `silver_orders`: `not_null` on `order_id`, `source_marketplace`, `total_amount`; `unique` composite on `(order_id, source_marketplace)`. Note: PRD §5.3 names `gross_order_value` / `net_payout_margin`; per pre-approved decisions, `total_amount` replaces `gross_order_value` (the actual Otter field) and `net_payout_margin` is deferred to PR4 (it requires COGS).
   - `silver_reports`: `not_null` on `job_id`, `result_status`, `gross_sales_amount`, `net_payout_amount`; `unique` on `job_id`.
   - **Null policy** (per PRD §5.3): `not_null` test on revenue variables + a custom dbt singular test in `tests/` that asserts 0 rows with status=`WARN` (the model itself does not default to 0.00 — that policy lives in Gold, PR4). Silver flags the null and stops the build. Documented in the proposal and spec.
8. **Integration test harness** — `pytest` integration test that:
   - Spins up `moto[s3]` with Bronze objects seeded from `tests/fixtures/otter/orders_response.json` etc.
   - Runs `dbt build --project-dir dbt_project/ --profiles-dir <tmp>` against a temporary DuckDB file, configured with `filesystems: [s3]` pointing at `endpoint_url=http://localhost...` (moto S3 endpoint) for hermetic local runs.
   - Asserts the Silver Parquet output has the expected row count, column types, and that `dbt test` exits 0.
9. **`omc-ingest run-silver` CLI subcommand** (PR3b, optional) — Click subcommand that invokes `dbtRunner().invoke(['build', '--project-dir', 'dbt_project/', '--profiles-dir', '<runtime-resolved>'])` and writes a `pipeline_execution_logs` row via the existing `LogsPort` wiring. Failure path exits non-zero. If the dbt subprocess integration is too invasive, this is dropped from PR3b to keep the PR under 400 lines.

### Out of Scope (PR4+)

- **PII SHA-256 masking with salt** — `customer_name_hash` / `customer_phone_hash` are copied **raw** in PR3. Salt + re-hash lands in PR4 (where `merchant_credentials.salt` or a per-tenant secret in `SecretsPort` provides the salt).
- **Gold star schema** (`fact_financial_sales`, `dim_menu_catalog`) — PRD §3.2, PR4+.
- **`merchant_cogs` table** + COGS joins — PRD §3.1, PR4 (or PR5 with the UI).
- **Streamlit UI** + COGS editor + KPI cards + charts — PRD §6, PR5.
- **OAuth `authorization_code` flow** + onboarding wizard — PR5.
- **Cron / EventBridge scheduling** — deployment concern, not PR3.
- **Backfill resumability** + parallel backfill — out of scope per PR2b lock.
- **PostgresBlobStore for KMS ciphertext** (mentioned as PR2a follow-up) — out of scope; PR3 reads S3, not Postgres.

## Capabilities

### New Capabilities

- `silver-transformation`: dbt project + `silver_orders` + `silver_reports` + dbt tests + pytest integration harness. Covers PRD §3 (Silver portion) and PRD §5.3.

### Modified Capabilities

- `bronze-ingestion`: delta — Bronze S3 path contract (SCN-014, already in `bronze-ingestion/spec.md`) is now consumed by a downstream dbt reader. No behavioral change to Bronze writers; just adds a documented contract that Silver relies on: "the Otter `orders` JSON is a top-level array under the `orders` key, and report JSONs use `result.{totals, period_*}` schema."
- `local-test-mocking`: delta — `dbt build` is now exercised by an integration test against moto S3 + a temp DuckDB file. The existing `responses` + `moto[s3,kms]` + `testcontainers[postgres]` stack is preserved; no new mocking libraries required.

## Approach

- **Strict TDD** per `apply.tdd: true` — RED → GREEN → REFACTOR per dbt model and per test.
- **Hexagonal layering** preserved: dbt is invoked by Python via `dbtRunner` (or a CLI shim), not called as a subprocess. This keeps the `LogsPort` / `SecretsPort` wiring consistent.
- **S3-direct read** as the default, **local mirror** as a dev/test target. The profile's `target:` is selected by `OMCAE_DBT_TARGET` env var (`prod_s3` default, `local_mirror` for dev/CI). Local mirror points at a path on disk where a `make mirror-bronze` step has copied the most recent Bronze objects.
- **Composite `unique_key`** verified for dbt-duckdb's `merge` strategy: per dbt-duckdb README, `unique_key: ['order_id', 'source_marketplace']` (a list) is supported and produces `ON (s.order_id = d.order_id AND s.source_marketplace = d.source_marketplace)`.
- **Idempotency for the join across re-runs** (PR2b contract): Silver uses DuckDB's `filename` virtual column to extract `run_timestamp_utc` from the Bronze object name; in `is_incremental()`, it filters to `run_timestamp_utc > (SELECT MAX(...) FROM this)` so re-runs only process new timestamps. This is a "latest-wins" merge consistent with PR2b's idempotency contract.
- **Null policy** (per PRD §5.3): Silver's dbt `not_null` test on `total_amount` is a hard fail. The 0.00 default + anomaly flag lives in Gold (PR4). Documented in the proposal and the Silver spec.

## Design Forks Resolved

| Fork | Options | Chosen | Rationale |
|------|---------|--------|-----------|
| Where dbt reads from | (A) S3 direct via DuckDB `httpfs`; (B) local mirror only; (C) Postgres-staged Bronze | **A (S3 direct), with B fallback target** | PRD §3.1 calls for dbt reading Bronze; S3-direct avoids a sync step. Local mirror is required for hermetic CI because moto S3 isn't reachable from a hosted dbt-duckdb process without `endpoint_url`. |
| Materialization | (A) `view`; (B) `table`; (C) `incremental` | **C (`incremental`)** | PR2b's idempotency contract (latest-wins re-runs) maps cleanly to `incremental` + `merge`. Avoids re-scanning the entire Bronze bucket on every run. |
| Incremental strategy | (A) `append`; (B) `delete+insert`; (C) `merge` | **C (`merge`)** | Composite `unique_key` for `silver_orders` requires `merge` to dedupe on `(order_id, source_marketplace)`. `delete+insert` would delete by composite key but rebuild full rows; `merge` is cheaper on update. |
| Test framework | (A) dbt's own `dbt test`; (B) pytest against the materialized Parquet; (C) both | **C (both)** | dbt's own test framework runs `not_null` / `unique` inside the dbt build (catches issues before Parquet is written). pytest integration test runs the full `dbt build` end-to-end and asserts row counts + types on the Parquet file. pytest is opt-in via `-m integration` to keep unit-test loop fast. |
| PII masking in PR3 | (A) salted SHA-256 in Silver; (B) raw copy in Silver; (C) defer entirely | **B (raw copy, defer salt to PR4)** | PRD §3.2 mandates salted SHA-256, but the salt's storage location (`merchant_credentials` field? a per-tenant SecretsPort field?) is a PR4 design decision. Copying raw now keeps Silver's spec stable; PR4 will swap the columns in place via `dbt run --full-refresh` on `silver_orders`. |
| Single PR vs. split | (A) single ~600-LOC PR; (B) split PR3a + PR3b | **B (split)** | Single PR exceeds the 400-line review budget. Split is autonomous, reversible, and matches the chained-PR pattern from PR1 → PR2a → PR2b. |

## Affected Areas

### PR3a (forecast ~350 LOC delta)

| File | Impact | Approx LOC | Notes |
|------|--------|-----------|-------|
| `pyproject.toml` | Modified | 6 | Add `dbt-core`, `dbt-duckdb` |
| `dbt_project/dbt_project.yml` | New | 25 | name, profile, model paths, materialization defaults |
| `dbt_project/profiles.yml` | New | 30 | Two targets: `prod_s3` (httpfs + secrets) and `local_mirror` |
| `dbt_project/models/silver/silver_orders.sql` | New | 65 | CTE: read_json_auto → unnested line items → typed columns |
| `dbt_project/models/silver/silver_orders.yml` | New | 35 | schema + `not_null` + `unique` composite tests |
| `dbt_project/models/silver/_sources.yml` | New | 25 | `bronze.orders` source with `external_location` |
| `dbt_project/tests/silver_orders_not_null_revenue.sql` | New | 12 | Singular test documenting the null policy |
| `dbt_project/macros/parse_bronze_filename.sql` | New | 15 | Regex macro to extract `run_timestamp_utc` from filename |
| `tests/integration/test_dbt_silver_orders.py` | New | 90 | moto S3 + temp DuckDB + `dbt build` + Parquet shape assertions |
| `tests/unit/transformation/test_dbt_project_yml.py` | New | 25 | dbt project parses, profile loads, model count |
| `README.md` | Modified | 25 | "Silver transformation" subsection + `make silver` target |

### PR3b (forecast ~250 LOC delta)

| File | Impact | Approx LOC | Notes |
|------|--------|-----------|-------|
| `dbt_project/models/silver/silver_reports.sql` | New | 75 | CTE: two sources joined by filename timestamp; final wide row |
| `dbt_project/models/silver/silver_reports.yml` | New | 35 | schema + `not_null` + `unique` on `job_id` |
| `dbt_project/models/silver/_sources.yml` | Modified | 15 | add `bronze.reports_enqueue` + `bronze.reports_result` |
| `dbt_project/macros/parse_report_filename.sql` | New | 10 | Filename → run_timestamp_utc for reports |
| `dbt_project/tests/silver_reports_unique_job_id.sql` | New | 10 | Singular test asserting job_id uniqueness |
| `src/omc_analytics/transformation/dbt_runner.py` | New | 35 | thin wrapper around `dbtRunner`; resolves project/profiles dir, wires `LogsPort` |
| `src/omc_analytics/ingestion/run.py` | Modified | 15 | add `run-silver` Click subcommand |
| `tests/integration/test_dbt_silver_reports.py` | New | 50 | moto S3 + temp DuckDB + `dbt build --select +silver_reports` + assertions |
| `tests/unit/transformation/test_dbt_runner.py` | New | 20 | dbtRunner wrapper logs SUCCESS/FAILED to LogsPort |
| `README.md` | Modified | 15 | "Reports Silver" + "Running Silver locally" |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| dbt-duckdb version drift (DuckDB 1.x → 2.x) | Med | Pin `dbt-duckdb>=1.8,<2.0`; document upgrade procedure in PR4 |
| dbt test framework triggers long CI runs | Med | `pytest -m integration` opt-in; unit-test default skips dbt build |
| moto S3 endpoint URL not reachable from dbt-duckdb subprocess | Med | Use `filesystems:` config (fsspec) with `endpoint_url`, OR run dbt in-process via `dbtRunner` (not subprocess) — chose `dbtRunner` in design |
| Composite `unique_key` not supported on older dbt-duckdb | Low | Pinned >=1.8; README and tests assert list-form unique_key works |
| Otter API orders JSON is a top-level array vs object — `read_json_auto` shape mismatch | Med | Documented in `_sources.yml`; integration test seeds an array-shaped fixture; failure mode is loud (dbt compile error) |
| PR3b's `run-silver` CLI subcommand bloats the PR past 400 lines | Med | Marked optional in §In Scope; drop if PR3b is over budget after PR3a is reviewed |
| `dbtRunner` invocation path doesn't get LogsPort output in real time | Low | Use dbt's `callbacks=[...]` to stream events into the existing Python logger; test asserts a log row exists post-run |

## Rollback Plan

1. Revert PR branch.
2. `uv remove dbt-core dbt-duckdb` (or whichever PR is rolled back).
3. Delete `dbt_project/` directory. No S3 cleanup: Silver writes to its own bucket and any materialized objects are inert without consumers.
4. No DB migrations to revert.
5. The `run-silver` subcommand (PR3b) is additive; if rolled back, the Click command disappears and `omc-ingest` returns to its PR2b surface.

## Dependencies

**Runtime (new in PR3)**: `dbt-core>=1.8,<2.0`, `dbt-duckdb>=1.8,<2.0`. **Existing**: `boto3`, `click`, `pydantic`. **AWS**: S3 read IAM on the Bronze bucket (new permission for the dbt job's role). **Env vars (new)**: `OMCAE_S3_REGION`, `OMCAE_S3_ACCESS_KEY_ID`, `OMCAE_S3_SECRET_ACCESS_KEY`, `OMCAE_DBT_TARGET` (`prod_s3` | `local_mirror`), `OMCAE_DBT_BRONZE_BUCKET`, `OMCAE_DBT_SILVER_BUCKET`, `OMCAE_DBT_PROFILES_DIR` (optional, defaults to `~/.dbt`).

## Success Criteria

### PR3a

- [ ] `uv sync` adds dbt-core + dbt-duckdb cleanly
- [ ] `dbt_project/` parses; `dbt parse` exits 0
- [ ] `dbt build --select silver_orders` materializes the Parquet table against moto S3 + a seeded fixture
- [ ] All `not_null` and `unique` tests pass for `silver_orders`
- [ ] Integration test (`pytest -m integration tests/integration/test_dbt_silver_orders.py`) green
- [ ] ruff + mypy + black clean
- [ ] Forecast ≤ 400 LOC held for the PR

### PR3b

- [ ] `dbt build` runs both `silver_orders` and `silver_reports` end-to-end
- [ ] All dbt tests pass for `silver_reports` (`unique` on `job_id`)
- [ ] `omc-ingest run-silver` CLI subcommand works locally (if kept)
- [ ] Integration test for `silver_reports` green
- [ ] `LogsPort` receives a SUCCESS or FAILED row after each `run-silver` invocation
- [ ] Forecast ≤ 400 LOC held for the PR

## Review Budget (umbrella)

- Estimated gross changed lines: **~600 LOC** (PR3a ~350 + PR3b ~250)
- Estimated net (production code only): **~350 LOC** (most of the gross is tests + dbt YAML/macros)
- **400-line budget risk: High**
- **Chained PRs recommended: Yes**
- **Decision needed before apply: Yes** (orchestrator surfaces PR3a/PR3b split to user)
- Delivery strategy: `ask-on-risk` on the umbrella; once split, each child PR runs as `single-pr` (each ≤ 400 LOC gross).

---

*Proposal created by sdd-propose sub-agent · omnichanel-analytics project · change: silver-transformation-pr3 · 2026-06-11*
