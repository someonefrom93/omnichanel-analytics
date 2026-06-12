# Tasks: Backfill Loop (PR2b)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~431 gross / ~290 net code |
| File count | 8 (4 prod + 3 test + README) |
| Test count | 10 new + 9 updated mechanically |
| 400-line budget risk | Low (user approved `exception-ok`; gross exceeds 400 by ~31, net well under) |
| Chained PRs recommended | No (single PR per user decision) |
| Delivery strategy | exception-ok |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

---

## Phase 1: SCN-014 Delta — Foundation for Backfill

- [ ] 1.1 **Extend `build_bronze_key` signature** — Add required `target_date: date` param. Partition from `target_date`; filename from `run_timestamp_utc`. Files: `ingestion/bronze_keys.py`. Spec: §MODIFIED SCN-014 (3 scenarios). Design: §build_bronze_key delta.
  - RED: Write 3 new tests (`test_target_date_determines_partition`, `test_run_timestamp_determines_filename_only`, `test_rerun_same_target_date_same_partition_distinct_filename`). All fail.
  - GREEN: Update `build_bronze_key(...)` to accept and use `target_date`. 3 new + 9 existing tests pass (`target_date=run_ts.date()` preserves old partition for T-1).
  - REFACTOR: Verify key pattern still matches `r"^otter/merchant_id=..."`. ~10 LOC delta.
  - Done when: 12 tests green, ruff clean.

- [ ] 1.2 **Update `BronzeWriter.write_raw`** — Accept and forward `target_date: date` param. Update `write_report_pair` signature. Files: `ingestion/bronze_writer.py`. Spec: §MODIFIED SCN-014. Design: §BronzeWriter delta.
  - RED: Update 1-2 existing tests to pass `target_date`; add 1 test for `target_date` forwarding. Tests fail.
  - GREEN: Implement forwarding; 3 writer tests green. ~10 LOC delta.
  - REFACTOR: Confirm `write_report_pair` passes `target_date` to both inner calls.
  - Done when: writer tests green, moto-based tests pass.

## Phase 2: Pure Helpers

- [ ] 2.1 **`compute_window_for_date`** — Pure function: `target_date + store_tz → (start_utc, end_utc)`. Files: `ingestion/run.py`. Spec: §Daily Window Computation (1 scenario). Design: §compute_window_for_date.
  - RED: Write 1 test (Buenos Aires, date(2026,6,9)). Fails (function doesn't exist).
  - GREEN: Implement with `ZoneInfo` + `replace(hour=0/23:59:59.999999)` + `.astimezone(UTC)`. Test passes. ~12 LOC.
  - REFACTOR: Extract timezone helper if needed.
  - Done when: 1 test green.

- [ ] 2.2 **Refactor `compute_t1_window`** — Delegate to `compute_window_for_date`. Files: `ingestion/run.py`. Spec: §T-1 Window Regression (1 scenario). Design: §compute_t1_window refactor.
  - RED: Write 1 regression test asserting `compute_t1_window(...)` == `compute_window_for_date(date(...), tz)`. Fails until refactor.
  - GREEN: Replace body with `return compute_window_for_date((now_utc - timedelta(days=1)).date(), store_tz)`. New + 2 existing T-1 tests green. ~2 LOC delta.
  - REFACTOR: Verify existing DST transition test still passes.
  - Done when: 3 T-1 tests green.

- [ ] 2.3 **`compute_backfill_dates`** — Pure function with `[1, 90]` validation. Files: `ingestion/run.py`. Spec: §Backfill Date Computation (4 scenarios). Design: §compute_backfill_dates.
  - RED: 4 tests (default 30, custom 5, days=0 rejected, days=91 rejected). All fail.
  - GREEN: Implement list comprehension + `ValueError` guard. 4 tests green. ~8 LOC.
  - REFACTOR: None needed; pure function.
  - Done when: 4 tests green.

## Phase 3: RunContext Delta

- [ ] 3.1 **Add backfill fields to `RunContext`** — `backfill: bool = False`, `backfill_days: int = 30`. Files: `common/config.py`. Design: §RunContext delta.
  - No new tests (field-only; behavior tested in Phase 4-5). ~6 LOC.
  - Done when: mypy clean on config.py.

## Phase 4: Orchestrator Extension

- [ ] 4.1 **Extend `run_bronze_impl` with override kwargs** — `run_id_override`, `run_timestamp_override`, `target_date` kwargs (all `None` default). T-1 path unchanged when `target_date is None`. Files: `ingestion/run.py`. Design: §run_bronze_impl extension.
  - RED: Update 1 test to call with `target_date=date(2026,6,9)`; assert S3 partition reflects day=09. Fails (old signature).
  - GREEN: Add kwargs, compute window from `target_date` if set, forward to writer. Test passes. ~15 LOC.
  - REFACTOR: Ensure existing 3 `run_bronze_impl` tests unchanged (no kwargs → T-1 behavior preserved).
  - Done when: All run_bronze_impl tests green.

- [ ] 4.2 **`run_bronze_with_backfill` wrapper** — Loop over `compute_backfill_dates`, fresh `run_id` per iteration, fail-soft, returns 0/1. Files: `ingestion/run.py`. Spec: §Backfill Loop Iteration (3 scenarios). Design: §run_bronze_with_backfill.
  - RED: 3 tests (happy path 3 days → 3 log rows, fail-soft iteration 2 fails → iteration 3 runs, CLI exit non-zero on any FAILED). All fail. Mock `run_bronze_impl`.
  - GREEN: Implement loop + try/except per iteration. Tests pass. ~25 LOC.
  - REFACTOR: Extract iteration body if needed.
  - Done when: 3 wrapper tests green.

## Phase 5: Click CLI Delta

- [ ] 5.1 **Add `--backfill`/`--backfill-days` flags + wiring** — `click.IntRange(1,90)` for days; wire to `run_bronze_with_backfill` when `backfill=True`. Files: `ingestion/run.py`. Spec: §Click CLI (2 scenarios). Design: §Click CLI delta.
  - RED: 2 tests via `CliRunner` (`--backfill-days 0` → non-zero exit; `--backfill-days 91` → non-zero exit). Both fail.
  - GREEN: Add Click options; `_build_deps` gains `backfill` + `backfill_days` kwargs; CLI branches on `backfill`. Tests pass. ~25 LOC.
  - REFACTOR: Verify `--no-backfill` default → existing T-1 behavior unchanged.
  - Done when: 2 CLI tests green, `--help` shows new flags.

## Phase 6: Polish

- [ ] 6.1 **README "Backfill" subsection** — Document `--backfill` semantics, idempotency contract (partition stable, filename run-distinct), Silver (PR3) picks latest. Files: `README.md`. ~30 LOC.
  - Done when: Subsection present, no typos.

- [ ] 6.2 **Full verification** — `uv run pytest`, `uv run ruff check src/ tests/`, `uv run mypy src/omc_analytics/`, `uv run black --check .`. All proposal success criteria green.
  - Done when: All checks pass, ≥80% coverage on run.py.
