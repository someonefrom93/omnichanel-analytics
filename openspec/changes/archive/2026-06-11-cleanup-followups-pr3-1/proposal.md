# Proposal: Cleanup Follow-ups — PR3.1

## Intent

Bundle three WARNINGs from previously-archived PRs (PR2a, PR2b, PR3a) into one small, shippable unit that closes outstanding review feedback without adding new behavior. The change is mechanical: two test additions that exercise code paths that already exist, plus a single docstring that makes the CLI exit-code contract explicit. This keeps the change diff small, low-risk, and within the 400-line review budget.

## Scope

### In Scope

- **PR2a.1** — Add two unit tests in `tests/unit/common/test_postgres_logs.py` that exercise the `update_finished` error path (psycopg2.Error → `PostgresLogsError` wrapping) and the `_acquire()` exception path (putconn guarantee when the SQL raises mid-block). Goal: lift `postgres_logs.py` coverage from 72% to 80%+. No production code changes.
- **PR2b.1** — Add a docstring note to `run_bronze_with_backfill` in `src/omc_analytics/ingestion/run.py` explicitly stating the return value is propagated to the OS via `sys.exit(return_code)` in the CLI handler. No logic change.
- **PR3a.1** — Add an idempotency re-run test for the `silver_orders` dbt model: invoke `dbt build --select silver_orders` twice against the same pre-seeded fixture and assert the row count is invariant after the second run. This validates the `incremental + merge` contract declared in `silver_orders.sql` lines 3-6 (`unique_key=['order_id', 'source_marketplace']`).

### Out of Scope

- Any new production behavior, refactor, or feature work.
- Gold-layer work, Streamlit, or PR3b/Silver-reports follow-ups.
- Migration of the `OMCAE_USE_LOCAL_BRONZE` deviation (deferred to PR4 per the model comment).
- Coverage work for any module other than `postgres_logs.py`.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
None — this change does not alter any spec-level requirement. The two test additions and the docstring comment are implementation-level follow-ups that close WARNINGs without changing observable behavior of the system. The existing specs in `openspec/specs/{bronze-ingestion, real-adapters-pr2a, silver-orders-pr3a}/` remain authoritative.

## Approach

1. **PR2a.1** — Mirror the existing `TestPostgresLogsPoolBehavior` pattern (mock `ThreadedConnectionPool`, assert `putconn` call count). Add `test_update_finished_wraps_psycopg2_error_as_postgres_logs_error` (cursor.execute raises psycopg2.Error, expect `PostgresLogsError`) and `test_acquire_releases_connection_on_exception` (getconn raises, expect the exception to propagate AND putconn to be skipped/handled per current contract). Reuse `_make_run_log` helper.
2. **PR2b.1** — One-line docstring amendment to `run_bronze_with_backfill` (lines 358-371 of `run.py`). The existing docstring already says "The caller (CLI) should propagate this exit code to the OS." Tighten this to name `sys.exit(return_code)` explicitly, citing line 618 of the same file. No imports, no logic.
3. **PR3a.1** — Extend `tests/integration/test_dbt_silver_orders_e2e.py` (or add a sibling file `test_dbt_silver_orders_idempotency.py`) with `test_silver_orders_idempotent_under_rerun`. Reuse `_dbt_via_dbtRunner` and the moto S3 + DuckDB pre-seed pattern already in the file. After the first successful run, query `SELECT COUNT(*) FROM silver_orders`, then invoke `dbt build --select silver_orders` a second time, then assert the count is unchanged.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `tests/unit/common/test_postgres_logs.py` | Modified | Add 2 tests (~40 LOC) covering `update_finished` error wrapping and `_acquire` exception path |
| `src/omc_analytics/ingestion/run.py` | Modified | Add 1-2 lines of docstring to `run_bronze_with_backfill` naming `sys.exit(return_code)` |
| `tests/integration/test_dbt_silver_orders_e2e.py` (or new sibling) | Modified or New | Add 1 idempotency re-run test (~60-80 LOC) reusing the existing moto/DuckDB fixture pattern |
| `src/omc_analytics/common/postgres_logs.py` | Unchanged | Coverage target only — no production edits |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Idempotency test is flaky if moto S3 state leaks between runs | Low | The existing test uses `tmp_path` per-test and `mock_aws()` context — same pattern applies; DuckDB file is per-test. |
| New `postgres_logs` tests accidentally exercise production code paths | Low | Use the same `patch.object(psycopg2.pool, "ThreadedConnectionPool")` mock pattern already in `TestPostgresLogsPoolBehavior`. No real DB needed. |
| Docstring change accidentally breaks doc tests / linting | Very Low | Docstring is plain English; no reST cross-references; ruff/mypy are docstring-tolerant. |
| Coverage does not reach 80% even after the two new tests | Low | If the gap remains, add a third test for the `_acquire` happy path (no exception → putconn called once) to be safe. |

## Rollback Plan

Revert the single commit. All three follow-ups are additive:
- Removing the two unit tests returns `postgres_logs.py` coverage to ~72% (the original WARNING state) — no behavior change.
- Removing the docstring amendment reverts the comment, leaving the function behavior identical.
- Removing the idempotency test simply removes a new integration test — no production impact.

No data, schema, or migration concerns. A plain `git revert` is sufficient.

## Dependencies

- `tests/unit/common/test_postgres_logs.py` already imports `psycopg2` and `psycopg2.pool` inside the test methods (lazy import pattern at lines 153-154, 181-182). The new tests can use the same lazy import to keep the test file's top-level imports clean.
- The idempotency test reuses `_dbt_via_dbtRunner` from the existing integration test file; no new fixtures required.
- The dbt fixture `tests/fixtures/otter/orders_response.json` is already committed and used by the existing e2e test.

## Success Criteria

- [ ] `postgres_logs.py` line coverage ≥ 80% (was 72%), verified via `pytest --cov=src --cov-report=term-missing`.
- [ ] `run_bronze_with_backfill` docstring explicitly names `sys.exit(return_code)` as the propagation mechanism.
- [ ] New idempotency test passes locally with `pytest -m integration`; second `dbt build --select silver_orders` run produces the same row count as the first.
- [ ] All existing tests still pass (`pytest`).
- [ ] Total changed lines ≤ 200 (well under the 400-line PR review budget).
- [ ] No production behavior change: `git diff` against `src/` shows only the docstring amendment.
