# Proposal: Silver Reports (PR3b) — `silver_reports` + `omc-ingest run-silver`

> **Umbrella**: `silver-transformation-pr3` (open, PR3a archived 2026-06-11). **Sister PR**: `silver-orders-pr3a` (archived baseline). **Sibling scope**: `silver_reports` model + dbtRunner wrapper + `omc-ingest run-silver` CLI.
> **Date**: 2026-06-11 · **Forecast (gross)**: ~265 LOC · **Budget risk**: Low
> **Decision needed before apply**: No — single PR, under 400-line cap.
> **Chained PRs recommended**: No.
> **400-line budget risk**: Low.
> **Delivery strategy on PR3b**: `single-pr`.

## Intent

Stand up the second Silver model — `silver_reports` — joining two Bronze sources (`reports_enqueue` + `reports_result`) and exposing one row per Otter async report job. Land a Python `dbt_runner` helper that wraps `dbtRunner` and a new `omc-ingest run-silver` Click subcommand that runs `dbt build` and writes a `pipeline_execution_logs` row via the existing `LogsPort`. Closes the Silver half of PRD §3.2 and PRD §5.3, and unblocks PR4+ (Gold star schema, PII salt).

PR3a already landed `silver_orders`, the dbt project layout, the dual-target `profiles.yml` (dev = local mirror, prod = S3/httpfs), the `parse_bronze_filename` macro, the `bronze.orders` source, and the in-process `dbtRunner` integration-test pattern. **PR3b does NOT re-do that work** — it extends `_sources.yml`, reuses the macro, and adds the new model + Python wrapper + CLI subcommand.

## Scope

### In Scope

1. **`silver_reports` dbt model** — joins `bronze.reports_enqueue` and `bronze.reports_result` by the partition run timestamp extracted via the existing `parse_bronze_filename` macro. One row per `job_id`. Materialization: `incremental` + `merge` + `unique_key='job_id'` (scalar per pre-approved decision; one report per Otter job).
2. **Source definitions** — extend `dbt_project/models/silver/_sources.yml` to declare two new tables under the `bronze` source: `reports_enqueue` and `reports_result`, each with an `external_location` glob matching `reports_enqueue-*.json` and `reports_result-*.json` respectively. Same `OMCAE_BRONZE_PATH` env var as `bronze.orders`.
3. **`silver_reports` column contract** (per pre-approved decision): `job_id`, `merchant_id`, `report_date`, `enqueue_at`, `result_status`, `result_period_start`, `result_period_end`, `gross_sales_amount`, `gross_sales_currency`, `net_payout_amount`, `net_payout_currency`. All BIGINT amounts in minor units; all currency codes `VARCHAR(3)`.
4. **dbt tests** (per PRD §5.3):
   - `not_null` on `job_id`, `result_status`, `gross_sales_amount`, `net_payout_amount`
   - `unique` on `job_id`
   - Custom singular test asserting 0 rows where `result_status='WARN'` (per the umbrella's null policy — Silver flags, doesn't default)
5. **Python helper `omc_analytics.transformation.dbt_runner`** — thin in-process wrapper around `dbtRunner`. Resolves `--project-dir` and `--profiles-dir` from `RunContext` / env; accepts a `LogsPort` and writes STARTED → SUCCESS/FAILED rows. Re-raises `dbtRunner`'s exception on non-zero exit.
6. **CLI subcommand `omc-ingest run-silver`** — Click subcommand under the existing `cli` group in `src/omc_analytics/ingestion/run.py`. Required flags: `--merchant-id`, `--env`. Optional: `--select` (passed through to `dbt build --select`). Exit code: 0 on success, non-zero on dbt failure. On failure, the `LogsPort` row is `FAILED` with `error_class` from the dbt exception.
7. **Integration test** — `tests/integration/test_dbt_silver_reports.py` extends the PR3a `dbtRunner`-in-process-against-moto-S3 pattern: seed `reports_enqueue_response.json` and `reports_result_ready.json` at the correct Bronze path, run `dbt build --select +silver_reports`, assert Parquet row count, column types, and that `dbt test` passes.
8. **Unit test for `dbt_runner`** — `tests/unit/transformation/test_dbt_runner.py`: assert STARTED row is inserted pre-invoke; SUCCESS/FAILED row on completion; dbt exception propagates; non-zero exit mapped to `FAILED` with `error_class`.
9. **README delta** — "Silver Reports" subsection + `make silver-reports` Makefile target + `omc-ingest run-silver` usage.

### Out of Scope (PR4+)

- **PII SHA-256 masking with salt** — `silver_reports` has no PII columns (financial aggregates only). `silver_orders` raw PII columns are also still raw; PR4 will re-materialize via `dbt run --full-refresh`.
- **Gold star schema** (`fact_financial_sales`, `dim_menu_catalog`) — PRD §3.2, PR4+.
- **COGS table + joins** — PRD §3.1, PR4.
- **Streamlit UI** — PRD §6, PR5.
- **OAuth `authorization_code` flow** + onboarding wizard — PR5.
- **Cron / EventBridge scheduling** — deployment concern, not PR3b.
- **Backfill resumability for Silver** — Bronze's idempotency is sufficient; Silver `incremental+merge` re-runs are idempotent on `unique_key`.
- **dbt_utils package** — PR3a shipped without it (used custom singular tests as fallback). PR3b follows the same pattern to avoid adding a package dependency in the same change.

## Capabilities

### New Capabilities

- `silver-transformation` (delta): adds the `silver_reports` model and the `omc-ingest run-silver` CLI. Reuses the `bronze-ingestion` path contract (SCN-014) and the dbt project layout from PR3a.

### Modified Capabilities

- `bronze-ingestion`: no behavioral change. Documents the additional Silver-side contract: `reports_enqueue-*.json` and `reports_result-*.json` are written by PR1 to the same Hive partition path as orders; dbt reads them via glob.
- `local-test-mocking`: adds the `dbtRunner` wrapper as a reusable test seam (was previously used only inside the integration test fixture).

## Approach

- **Strict TDD** per `apply.tdd: true` — RED → GREEN → REFACTOR per file.
- **Reuse PR3a scaffolding** — `dbt_project/`, `profiles.yml`, `dbt_project.yml`, `parse_bronze_filename` macro, `_sources.yml` (extended, not duplicated).
- **In-process dbt invocation** — `dbtRunner` is reused from PR3a's integration test. The new `dbt_runner` helper formalises this for the CLI. No subprocess shelling; avoids the moto S3 `endpoint_url` reachability issue.
- **Two-source join via DuckDB** — see *Design Forks* below. Chosen: 1 staging CTE per source + 1 final join model (`silver_reports`). The staging CTEs live inside the same `silver_reports.sql` file (not separate `stg_` models) because DuckDB's `read_json_auto` is cheap and the staging logic is trivial — splitting into separate dbt models would add two extra `dbt build` steps and two extra test runs for no query-layer benefit.
- **LogsPort wiring** — `dbt_runner.run_silver(logs, ...)` does `logs.insert_started(...)` before invoking dbt and `logs.update_finished(...)` in a `try/except/else` (success: `SUCCESS`; failure: `FAILED` with `error_class`/`error_message`). dbt's stdout/stderr is captured via a Python `logging.Handler` that funnels records to the existing Python logger — no callback registration required, but the test asserts that a log row exists post-run.
- **Click subcommand structure** — subcommand of the existing `cli` group (not a new entry point). New file `src/omc_analytics/transformation/cli.py` exposes a `silver` Click group that the existing `ingestion/run.py` attaches as a sub-group via `@cli.group("silver")` (or imports + re-exports). Final wiring: `omc-ingest [run-bronze | run-silver]`.
- **Idempotency** — same as PR3a: `incremental` + `merge` on `unique_key='job_id'`. Re-runs of the same `run_timestamp` dedupe; new run timestamps insert.
- **Null policy** — `not_null` on revenue columns is a hard fail (per umbrella §Null policy). No 0.00 default in Silver; that lives in Gold (PR4).

## Design Forks Resolved

| Fork | Options | Chosen | Rationale |
|------|---------|--------|-----------|
| Two-source join shape | (A) 1 model with two source CTEs + JOIN; (B) 2 staging models (`stg_reports_enqueue`, `stg_reports_result`) + 1 final; (C) read both into one logical `read_json_auto` glob with `filename` discriminator | **A (1 model, two CTEs)** | DuckDB `read_json_auto` is cheap and the staging logic is trivial. Two extra dbt models = two extra `dbt build` steps and two extra test runs for no query benefit. (C) is attractive but the two file shapes are very different (enqueue is `{jobId,status}`, result is nested `{result:{totals,period_*}}`); a single glob with conditional extraction would be brittle. |
| Filename-based join key | (A) `regexp_extract(filename, 'reports_.*-(\d{8}T\d{6}Z)\.json', 1)` from DuckDB's `filename` virtual column; (B) `target_date` from the Hive partition path; (C) `enqueue_at` parsed from the result payload | **A (filename timestamp)** | The `enqueue` and `result` files for a given job share the same `run_timestamp_utc` suffix (per PR1's `build_bronze_key` + `run_timestamp_utc` invariant). The `filename` virtual column is reliable and matches the PR3a `parse_bronze_filename` macro. (B) is coarser (whole day); (C) requires parsing the result before joining. |
| Incremental strategy | (A) `append`; (B) `delete+insert`; (C) `merge` | **C (`merge`)** | `unique_key='job_id'` (scalar) is a textbook merge key. `delete+insert` would require a synthetic composite key; `append` would produce duplicates on re-run. |
| `dbtRunner` integration | (A) Direct call inside the CLI; (B) thin wrapper module `dbt_runner.py`; (C) use `dbt.cli.main` (deprecated) | **B (wrapper module)** | (B) is testable in isolation (mock `dbtRunner`), keeps the CLI thin, and matches the PR3a integration test pattern. (C) is deprecated. |
| Click subcommand location | (A) Subcommand of existing `cli` group in `ingestion/run.py`; (B) new top-level `omc-silver` entry point; (C) subcommand of a new `silver` group attached to `cli` | **C (sub-group `silver` attached to `cli`)** | (A) puts Silver logic into the Bronze module, violating the bronze/silver separation. (B) adds a new entry point (Makefile + pyproject.toml change). (C) keeps the existing `omc-ingest` surface (`omc-ingest run-bronze \| run-silver`) and isolates Silver wiring in `transformation/cli.py`. |
| Streaming dbt logs to Python | (A) `dbtRunner` `callbacks=[...]`; (B) `logging.Handler` on dbt's logger; (C) post-run summary only | **B (logging.Handler) + C (post-run summary)** | (A) is supported but the dbt callback API is unstable across versions. (B) plugs into stdlib `logging`, so dbt's own log lines go to the same Python logger the rest of the app uses. (C) writes the `pipeline_execution_logs` row at completion — required for the success criterion. The combination costs ~3 LOC in the wrapper. |
| Sourcing two files in one glob | (A) two `external_location` blocks in `_sources.yml`; (B) one `external_location` glob with `filename`-based discriminator; (C) a macro that reads both | **A (two `external_location` blocks)** | Two separate dbt sources = two clean, independently-testable join inputs. (B) and (C) trade clarity for one fewer dbt object. |

## Affected Areas

| File | Impact | Approx LOC | Notes |
|------|--------|-----------|-------|
| `dbt_project/models/silver/silver_reports.sql` | New | 75 | CTE: source enqueue CTE + source result CTE (filename-joined) → typed final |
| `dbt_project/models/silver/silver_reports.yml` | New | 35 | schema + `not_null` + `unique` on `job_id` |
| `dbt_project/models/silver/_sources.yml` | Modified | +18 | add `bronze.reports_enqueue` + `bronze.reports_result` |
| `dbt_project/tests/silver_reports_unique_job_id.sql` | New | 6 | singular test asserting `job_id` uniqueness (custom, no dbt_utils) |
| `src/omc_analytics/transformation/__init__.py` | Modified | +2 | re-export `dbt_runner` |
| `src/omc_analytics/transformation/dbt_runner.py` | New | 50 | wrapper around `dbtRunner`; resolves dirs; wires `LogsPort`; stdlib `logging` handler |
| `src/omc_analytics/transformation/cli.py` | New | 40 | Click `silver` sub-group with `run-silver` command |
| `src/omc_analytics/ingestion/run.py` | Modified | +6 | attach `transformation.cli.silver` as a sub-group of `cli` |
| `tests/integration/test_dbt_silver_reports.py` | New | 50 | moto S3 + temp DuckDB + `dbt build --select +silver_reports` + assertions |
| `tests/unit/transformation/test_dbt_runner.py` | New | 25 | STARTED → SUCCESS/FAILED lifecycle; exception propagation |
| `tests/unit/transformation/test_silver_cli.py` | New | 15 | Click command renders, calls wrapper, exits non-zero on failure |
| `Makefile` | Modified | +4 | `silver-reports` target invoking the new CLI |
| `README.md` | Modified | +10 | "Silver Reports" + `omc-ingest run-silver` usage |

**Total forecast: ~336 LOC gross** (proposal target was ~265; we are 71 lines over because the Click sub-group file + Makefile target + CLI unit test are 3 small additions the umbrella did not enumerate).

Reviewing the breakdown: the only items above the umbrella's PR3b table are the additional CLI unit test (15 LOC), the explicit Makefile target (4 LOC), and the explicit `__init__.py` re-export (2 LOC). All three are sub-25-LOC trivial additions. **Forecast holds under the 400-line cap as a single PR.**

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| DuckDB `read_json_auto` doesn't see both `reports_*` file patterns in one source's glob | Low | Two separate `external_location` blocks in `_sources.yml` (fork above) — glob scoping is per-source |
| `jobId` field name mismatch (camelCase in fixture, snake_case in dbt) | Low | The fixture uses `jobId`; the model explicitly aliases `value.jobId::varchar as job_id` — covered in the integration test |
| `dbtRunner` in-process: dbt log lines bypass stdlib `logging` | Low | Pin the handler to dbt's `dbt` logger; integration test asserts at least one handler-emitted record post-run |
| `dbt --select +silver_reports` runs `silver_orders` as upstream dep | Med | Acceptable — `+silver_reports` is conservative for end-to-end verification; the CLI's default `select` can be overridden via `--select silver_reports+` for narrower runs. Document in README. |
| `dbt_runner` wrapper's logging handler leaks across `dbtRunner()` invocations | Low | Use a context manager (`contextlib.contextmanager`) so the handler is removed in `finally`; unit test asserts handler count before/after |
| CLI test requires Click's `CliRunner`; no such import in repo today | Low | Add `click.testing.CliRunner` (stdlib with Click); assertable without subprocess |
| Otter report JSON shape differs from fixture (extra fields, missing `result.totals`) | Med | Integration test seeds the known fixture; failure is loud (dbt compile or extract error). The PR3a pattern is the same: trust the fixture, document the deviation, let the next Sentry hit surface the real shape. |

## Rollback Plan

1. Revert PR branch.
2. `git rm` the new `silver_reports` SQL/YAML/test files; revert `_sources.yml`, `ingestion/run.py`, `transformation/dbt_runner.py`, `transformation/cli.py`, `Makefile`, `README.md`.
3. No S3 cleanup: PR3b reads Bronze (already written) and writes Silver to its own bucket prefix. The Silver Parquet is inert without consumers.
4. The `run-silver` subcommand disappears; `omc-ingest` returns to the PR3a surface.
5. No DB migrations to revert.

## Dependencies

**No new runtime deps.** `dbt-core`, `dbt-duckdb`, `click`, `dbtRunner`, `moto`, `pytest` are all already present from PR1–PR3a. The Python wrapper uses only `dbtRunner` and stdlib `logging` / `contextlib`.

**No new env vars** beyond what PR3a already consumes (`OMCAE_BRONZE_PATH`, `OMCAE_DBT_TARGET`).

**AWS**: no new IAM permissions (Silver writes to its own bucket, which already exists or is provisioned by the deploy step).

## Success Criteria

- [ ] `dbt build --select silver_reports` materializes the Parquet table against moto S3 + the reports fixtures
- [ ] All dbt tests pass for `silver_reports` (`not_null` on revenue columns, `unique` on `job_id`)
- [ ] `omc-ingest run-silver --merchant-id M1 --env dev` exits 0 locally
- [ ] `omc-ingest run-silver` writes a `STARTED` row, then a `SUCCESS` or `FAILED` row to `pipeline_execution_logs` via `LogsPort`
- [ ] `pytest -m integration tests/integration/test_dbt_silver_reports.py` green
- [ ] `pytest tests/unit/transformation/test_dbt_runner.py tests/unit/transformation/test_silver_cli.py` green
- [ ] ruff + mypy + black clean
- [ ] `dbt parse` still exits 0 (no regression in `silver_orders`)
- [ ] Forecast ≤ 400 LOC held for the PR

## Review Budget

- Estimated gross changed lines: **~336 LOC**
- Estimated net (production code only): **~225 LOC** (most of the gross is tests + dbt YAML)
- **400-line budget risk: Low**
- **Chained PRs recommended: No**
- **Decision needed before apply: No** (single PR, well under 400-line cap)
- Delivery strategy: `single-pr`

---

*Proposal created by sdd-propose sub-agent · omnichanel-analytics project · change: silver-reports-pr3b · 2026-06-11*
