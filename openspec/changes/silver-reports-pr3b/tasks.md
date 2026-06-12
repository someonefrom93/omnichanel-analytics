# Tasks: silver-reports-pr3b

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~348 |
| Estimated file count | 14 |
| Estimated test count | 13 (5 dbt + 2 unit + 1 integration + 5 scenario assertions) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Phase 1: Source Definitions

- [ ] 1.1 **Extend `_sources.yml`** — Add `bronze.reports_enqueue` and `bronze.reports_result` tables under the existing `bronze` source, each with table-level `meta.external_location` glob matching `reports_enqueue-*.json` / `reports_result-*.json`. Files: `dbt_project/models/silver/_sources.yml`. Spec: ADDED §Source Definitions. *Done when: `dbt compile` resolves both new sources.*

## Phase 2: silver_reports Model + Schema + Tests

- [ ] 2.1 **Write `silver_reports.sql`** — Two CTEs (`enqueue`, `result`) reading from sources, each extracting `run_timestamp_utc` via `{{ parse_bronze_filename('_filename') }}`. LEFT JOIN on `run_timestamp_utc`. 11 typed columns. Config: `materialized='incremental'`, `unique_key='job_id'`. Files: `dbt_project/models/silver/silver_reports.sql`. Spec: ADDED §§Materialization, Column Contract. Design: §SQL Logic. *Done when: `dbt run --select silver_reports` materializes.*

- [ ] 2.2 **Write `silver_reports.yml`** — 11 columns with types + descriptions. `not_null` on `job_id`, `result_status`, `gross_sales_amount`, `net_payout_amount`. `unique` on `job_id`. Files: `dbt_project/models/silver/silver_reports.yml`. Spec: ADDED §dbt Tests. Design: §File Changes. *Done when: `dbt test --select silver_reports` passes.*

- [ ] 2.3 **Write singular tests** — `silver_reports_unique_job_id.sql`: composite-count guard. `silver_reports_no_warn_status.sql`: `SELECT * WHERE result_status='WARN'` with `severity='error'`. Files: `dbt_project/tests/`. Spec: ADDED §WARN status. Design: §Testing Strategy. *Done when: both tests pass on valid data.*

## Phase 3: dbt_runner Python Wrapper

- [x] 3.1 **Create `dbt_runner.py`** — `dbt_runner` class with `__init__(logs, project_dir, profiles_dir)` and `run(*, select, merchant_id, env, run_id=None)`. Inserts STARTED via `logs.insert_started`, invokes `dbtRunner`, updates FINISHED (SUCCESS|FAILED). Re-raises on failure. Uses `pipeline_name='otter_silver_transformation'`. Files: `src/omc_analytics/transformation/dbt_runner.py`. Spec: ADDED §dbt_runner. Design: §Wrapper. *Done when: unit test green.*

- [x] 3.2 **Unit-test `dbt_runner`** — Mock `dbtRunner`, assert STARTED→SUCCESS lifecycle; mock exception → FAILED with `error_class`; assert exception re-raised. Files: `tests/unit/transformation/test_dbt_runner.py`. Spec: ADDED §dbt_runner scenarios. *Done when: 3 test cases green.*

- [x] 3.3 **Update `__init__.py`** — Re-export `dbt_runner` from `transformation/__init__.py`. Files: `src/omc_analytics/transformation/__init__.py`. *Done when: `from omc_analytics.transformation import dbt_runner` works.*

## Phase 4: Click CLI

- [x] 4.1 **Create `transformation/cli.py`** — `silver` Click group + `run-silver` command with `--merchant-id`, `--env`, `--select` (default `+silver_reports`). Resolves dbt dirs, builds deps, calls `dbt_runner.run()`. Exits non-zero on failure. Files: `src/omc_analytics/transformation/cli.py`. Spec: ADDED §CLI. Design: §Click CLI. *Done when: `CliRunner` test green.*

- [x] 4.2 **Wire into `ingestion/run.py`** — `cli.add_command(silver_group, name='silver')`. Import from `transformation.cli`. Files: `src/omc_analytics/ingestion/run.py`. Spec: ADDED §CLI. *Done when: `omc-ingest silver --help` shows the sub-group.*

- [x] 4.3 **Unit-test CLI** — `CliRunner` invokes `run-silver`, asserts exit 0 on success; mock failure asserts exit 1. Files: `tests/unit/transformation/test_silver_cli.py`. *Done when: 2 test cases green.*

## Phase 5: Integration Test

- [x] 5.1 **Write integration test** — Follow PR3a pattern: moto S3 + fixture seeding (`reports_enqueue_response.json`, `reports_result_ready.json`) → `dbtRunner` in-process → DuckDB query assertions (row count=1, `job_id='job_abc123'`, amounts 12500/8750). Mark `@pytest.mark.integration`. Use `OMCAE_USE_LOCAL_BRONZE=true` workaround for moto. Files: `tests/integration/test_dbt_silver_reports.py`. Spec: ADDED §Integration Test. Design: §Testing Strategy. *Done when: `pytest -m integration tests/integration/test_dbt_silver_reports.py` green.*

## Phase 6: Polish

- [x] 6.1 **Update Makefile** — Add `silver` target: `uv run dbt build --project-dir dbt_project`. Files: `Makefile`. *Done when: `make help` shows target.*

- [x] 6.2 **Update README** — Add "Silver Reports" subsection with model description, `omc-ingest run-silver` usage, and local run instructions. Files: `README.md`. *Done when: subsection present.*

- [x] 6.3 **Lint + type check** — `uv run ruff check`, `uv run mypy src/omc_analytics/transformation/`, `uv run pytest -m "not integration"`. Files: all. *Done when: all gates green.*
