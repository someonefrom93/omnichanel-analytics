# Tasks: Cleanup Follow-ups PR3.1

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~112 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Phase 1: PR2a.1 — PostgresLogs Error-Path Tests

- [x] 1.1 Add `test_update_finished_wraps_psycopg2_error` to `tests/unit/common/test_postgres_logs.py`: mock pool + cursor raising `psycopg2.Error` on execute, assert `PostgresLogsError` raised + `putconn` called once
- [x] 1.2 Add `test_acquire_releases_connection_on_exception` to same file: mock conn.cursor.side_effect = `psycopg2.Error`, call `insert_started`, assert `putconn` called once
- [x] 1.3 Run `uv run pytest tests/unit/common/test_postgres_logs.py -v` — all 10 tests green (8 existing + 2 new)

## Phase 2: PR2b.1 — Docstring Amendment

- [x] 2.1 Edit `run_bronze_with_backfill` docstring in `src/omc_analytics/ingestion/run.py`: add explicit `sys.exit(return_code)` reference after "The caller (CLI) should propagate..."
- [x] 2.2 Run `uv run ruff check src tests` — confirm no lint regressions

## Phase 3: PR3a.1 — Silver Orders Idempotency Test

- [x] 3.1 Add `test_silver_orders_idempotent_on_rerun` to `tests/integration/test_dbt_silver_orders_e2e.py`: reuse `_dbt_via_dbtRunner`, run `dbt build --select silver_orders` twice, assert `COUNT(*)` invariant. Mark `@pytest.mark.integration`
- [x] 3.2 Run `uv run pytest -m integration tests/integration/test_dbt_silver_orders_e2e.py -v`
- [x] 3.3 Run full suite: `uv run pytest` — 241 passed
- [x] 3.4 Run `uv run ruff check src tests` and `uv run mypy src/omc_analytics` — clean
- [x] 3.5 Commit: `6fe0598`
