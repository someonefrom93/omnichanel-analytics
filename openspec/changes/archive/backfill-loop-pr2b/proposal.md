# Proposal: Backfill Loop (PR2b)

> **Umbrella**: `real-adapters-backfill` (PR2). PR2a (KMSSecrets + PostgresLogs + config wiring) is **archived**. PR2b = backfill loop only.
> **Date**: 2026-06-11 · **Forecast**: ~290 LOC net / ~431 LOC gross · **Budget risk**: Low

## Intent

Wire PRD §2.1 "Historical Backfill Automation" into the Bronze ingestion orchestrator. Add `compute_backfill_dates` + `compute_window_for_date`, refactor `compute_t1_window` to be a special case, extend `run_bronze_impl` to iterate the last N days, expose `--backfill` / `--backfill-days N` Click flags. Hexagonal layering means adapter call sites do NOT change; only `ingestion/run.py` orchestration + a `target_date` param on `build_bronze_key` / `BronzeWriter.write_raw` (SCN-014 delta from the umbrella).

## Scope

### In Scope

1. `compute_backfill_dates(days, now_utc) -> list[date]` — pure; oldest-first, ending yesterday; raises `ValueError` outside `[1, 90]`.
2. `compute_window_for_date(target_date, store_tz) -> (start_utc, end_utc)` — pure; `compute_t1_window` becomes a 3-line call-through.
3. `run_bronze_impl(ctx, *, run_id_override=None, run_timestamp_override=None, target_date=None)` — `target_date=None` keeps T-1; otherwise uses the explicit date.
4. `run_bronze_with_backfill(ctx, days) -> int` — new wrapper; per-iteration fresh `run_id` + `run_timestamp_utc`; **fail-soft**; returns 0 if all SUCCESS, 1 if any FAILED.
5. Click flags — `--backfill/--no-backfill` (default `--no-backfill`) and `--backfill-days N` (int, default 30, `IntRange(1, 90)`). Defence-in-depth: Click + helper both validate.
6. `build_bronze_key` delta — `target_date: date` param (required). Partition from `target_date`; filename from `run_timestamp_utc`. SCN-014 delta.
7. `BronzeWriter.write_raw` delta — accept and forward `target_date`.
8. `RunContext` delta — `backfill: bool = False`, `backfill_days: int = 30`.
9. 10 new unit tests + 9 mechanical updates in `test_bronze_keys.py` + 1-2 in `test_bronze_writer.py`.
10. README — "Backfill" subsection in Production configuration.

### Out of Scope (PR3+)

Silver Parquet + "pick latest per partition" (PR3) · PII SHA-256 masking (PR4) · Gold star schema (PR4+) · Streamlit UI (PR5) · `merchant_cogs` (PR5) · OAuth `authorization_code` (PR5) · Webhooks (PR6+) · Cron/EventBridge scheduling (deployment) · PostgresBlobStore (PR2a follow-up) · Parallel backfill · Backfill resumability.

## Capabilities

### New Capabilities

- `backfill-loop`: full spec — CLI flags, daily-window iteration, idempotency contract, fail-soft, exit codes.

### Modified Capabilities

- `bronze-ingestion`: SCN-014 delta — partition reflects order/ingestion date, filename timestamp reflects run.

## Approach

**Idempotency contract** (umbrella-locked): re-running the same backfill day creates N timestamped objects under the same `day=DD` partition. Partition stable, filename run-distinct. Silver (PR3) picks the latest by filename lexicographic order.

**Fail-soft** (user-locked): each iteration's body in `run_bronze_impl` already wraps work in a try/except that writes a FAILED row before re-raising. The wrapper catches, counts, continues. CLI exits non-zero on any FAILED.

**Click wiring**: `_build_deps` signature gains `backfill` + `backfill_days` kwargs and forwards them into the new `RunContext` it returns (the CLI's pre-built `RunContext` is currently overwritten by `_build_deps` — confirmed in code).

## Affected Areas

| File | LOC delta | Notes |
|------|-----------|-------|
| `src/omc_analytics/ingestion/run.py` | 110 | helpers + wrapper + Click options |
| `src/omc_analytics/ingestion/bronze_keys.py` | 10 | `target_date` param |
| `src/omc_analytics/ingestion/bronze_writer.py` | 10 | forward `target_date` |
| `src/omc_analytics/common/config.py` | 6 | RunContext fields |
| `tests/unit/ingestion/test_run.py` | 180 | 10 new tests |
| `tests/unit/ingestion/test_bronze_keys.py` | 60 | 9 updated + 4 new |
| `tests/unit/ingestion/test_bronze_writer.py` | 25 | updated + 2 new |
| `README.md` | 30 | Backfill subsection |
| **Total** | **~431** | net code ≈ 290; test updates ≈ 141 (mechanical) |

## Design Forks Resolved

| Fork | Chosen | Rationale |
|------|--------|-----------|
| Partition key for backfill | Add `target_date` to `build_bronze_key` (SCN-014 delta) | Umbrella locks "order date for partition, run timestamp for filename" |
| Fail-soft vs fail-fast | Fail-soft; CLI exits non-zero on any FAILED | User spec: "fail-soft within the loop, but each iteration is independent" |
| Click validation | Both Click `IntRange` AND Python `ValueError` | Defence-in-depth |
| Per-iteration `run_id` | `run_id_override` kwarg on `run_bronze_impl` | Pure function stays pure; deterministic tests |

## Risks

| Risk | Mitigation |
|------|------------|
| 30× loop exceeds Otter rate limits | Serial (locked); PR1's 3-retry 429 backoff |
| Re-runs create N timestamped objects per partition | README documents; Silver (PR3) picks latest |
| `_build_deps` overwrites CLI's pre-built `RunContext` | `_build_deps` gains `backfill` + `backfill_days` kwargs |
| SCN-014 delta requires spec sync | One-line change; covered by `backfill-loop` spec's MODIFIED section |
| 9 existing `test_bronze_keys.py` tests need `target_date` | Mechanical update; all stay green (`target_date = run_ts.date()` reproduces old partition for T-1) |

## Rollback Plan

1. Revert PR branch. Click flags are additive (`--backfill` defaults to `--no-backfill`); existing users see no change.
2. No S3 cleanup: backfill-test objects live under correct partitions; inert once reverted.
3. `build_bronze_key`'s `target_date` is required (no default). mypy strict catches missed callers at CI.

## Success Criteria

- [ ] `pytest` green, ≥80% coverage on new modules
- [ ] 10 new unit tests pass; 9 existing `test_bronze_keys.py` tests updated and green
- [ ] `--backfill --backfill-days 3`: 3 distinct `run_id`, 6 log rows, 9 S3 objects
- [ ] Fail-soft: forced day-2 failure → 2 SUCCESS + 1 FAILED, day 1/3 objects present, CLI exits non-zero
- [ ] `--backfill-days 0` / `91` rejected by Click with non-zero exit
- [ ] `target_date` in S3 key matches order date, not run timestamp
- [ ] T-1 regression: `backfill=False` = 1 log row + 3 S3 objects
- [ ] No real AWS / Postgres / Otter call during `pytest -m "not integration"`
- [ ] ruff + mypy + black clean
- [ ] README "Backfill" subsection present

## Review Budget

- Estimated changed lines: **~290 net code / ~431 gross with tests**
- 400-line budget risk: **Low**
- Chained PRs recommended: **No** (single focused change)
- Delivery strategy: `exception-ok`

---

*Proposal created by sdd-propose sub-agent · omnichanel-analytics project · change: backfill-loop-pr2b · 2026-06-11*
