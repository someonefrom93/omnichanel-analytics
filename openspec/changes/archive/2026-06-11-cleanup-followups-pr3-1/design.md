# Design: Cleanup Follow-ups PR3.1

## Technical Approach

Three additive follow-ups with zero production code changes except one docstring line. Mirror existing test patterns: `TestPostgresLogsPoolBehavior` mocking (PR2a.1), inline docstring amendment (PR2b.1), and the moto S3 + DuckDB pre-seed + `_dbt_via_dbtRunner` pattern from `test_dbt_silver_orders_e2e.py` (PR3a.1).

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Mock pool for error-path tests | `patch.object(psycopg2.pool, "ThreadedConnectionPool")` + `MagicMock` conn/cursor | Real testcontainers Postgres | Existing `TestPostgresLogsPoolBehavior` uses this pattern; no new infrastructure needed |
| Idempotency test: new function vs new file | New function in existing file (`test_dbt_silver_orders_e2e.py`) | New sibling file | Reuses `_dbt_via_dbtRunner`, `_fetch_fixture_from_moto`, and the moto/DuckDB fixture pattern; single-file cohesion for silver_orders tests |
| Docstring amendment style | Explicit `sys.exit(return_code)` with line reference | General "propagate to OS" language | Removes ambiguity; cites line ~618 for grep-ability |
| Test exceptions for `_acquire` path | `mock_conn.cursor.side_effect = psycopg2.Error` | Raise on `getconn` | Mirrors `update_finished` error-path test pattern; exercises `finally: putconn` |

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `tests/unit/common/test_postgres_logs.py` | Modify | Add `test_update_finished_wraps_psycopg2_error` (mock conn, cursor raises on execute, expect PostgresLogsError + putconn) and `test_acquire_releases_connection_on_exception` (mock pool, cursor raises, expect putconn). ~40 LOC. |
| `src/omc_analytics/ingestion/run.py` | Modify | Amend `run_bronze_with_backfill` docstring to name `sys.exit(return_code)` explicitly. ~2 LOC. |
| `tests/integration/test_dbt_silver_orders_e2e.py` | Modify | Add `test_silver_orders_idempotent_on_rerun`: runs dbt build twice, asserts row count invariant. Reuses `_dbt_via_dbtRunner`. ~60 LOC. |

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | `update_finished` error wrapping | Mock pool + conn + cursor; assert `PostgresLogsError` raised + `putconn` called |
| Unit | `_acquire` exception path | Mock conn with `cursor.side_effect`; assert exception propagates + `putconn` called |
| Doc | `run_bronze_with_backfill` docstring | Visual inspection; ruff/mypy tolerate docstring changes |
| Integration | `silver_orders` idempotency | Two sequential `dbt build` calls via `_dbt_via_dbtRunner`; `COUNT(*)` invariant |
| Regression | Full suite | `uv run pytest` — expect 241-242 total (239 baseline + 3 new) |

## Risk: Coverage may not reach 80%

If the two new unit tests don't lift `postgres_logs.py` to 80%, add a third test for the `_acquire` happy path (no exception → putconn called once). This is covered in the proposal's mitigation table.

## Migration / Rollout

No migration required. All changes are additive. Rollback: `git revert` the single commit.
