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

- [ ] 1.1 Add `test_update_finished_wraps_psycopg2_error` to `tests/unit/common/test_postgres_logs.py`: mock pool + cursor raising `psycopg2.Error` on execute, assert `PostgresLogsError` raised + `putconn` called once
- [ ] 1.2 Add `test_acquire_releases_connection_on_exception` to same file: mock conn.cursor.side_effect = `psycopg2.Error`, call `insert_started`, assert `putconn` called once
- [ ] 1.3 Run `uv run pytest tests/unit/common/test_postgres_logs.py -v` — all 8 tests green (6 existing + 2 new)

## Phase 2: PR2b.1 — Docstring Amendment

- [ ] 2.1 Edit `run_bronze_with_backfill` docstring in `src/omc_analytics/ingestion/run.py`: add explicit `sys.exit(return_code)` reference after "The caller (CLI) should propagate..."
- [ ] 2.2 Run `uv run ruff check src tests` — confirm no lint regressions

## Phase 3: PR3a.1 — Silver Orders Idempotency Test

- [ ] 3.1 Add `test_silver_orders_idempotent_on_rerun` to `tests/integration/test_dbt_silver_orders_e2e.py`: reuse `_dbt_via_dbtRunner`, run `dbt build --select silver_orders` twice, assert `COUNT(*)` invariant. Mark `@pytest.mark.integration`
- [ ] 3.2 Run `uv run pytest -m integration tests/integration/test_dbt_silver_orders_e2e.py -v`
- [ ] 3.3 Run full suite: `uv run pytest` — expect ~241-242 tests
- [ ] 3.4 Run `uv run ruff check src tests` and `uv run mypy src/omc_analytics` — confirm clean
- [ ] 3.5 Commit with message: `test(postgres_logs): cover update_finished error path + _acquire exception path (PR2a.1)`, `doc(run): note sys.exit propagation in run_bronze_with_backfill (PR2b.1)`, `test(dbt): silver_orders idempotency re-run (PR3a.1)`
