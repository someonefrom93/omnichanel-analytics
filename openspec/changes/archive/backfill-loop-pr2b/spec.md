# Delta: Backfill Loop (PR2b)

> References: `openspec/specs/bronze-ingestion/spec.md` baseline. SCN-014 delta on §Bronze S3 Path Correctness.

---

## ADDED Requirements — Backfill Loop

### Requirement: Backfill Date Computation (Pure)

`compute_backfill_dates(days, now_utc)` MUST return a `list[date]` oldest-first ending yesterday. MUST raise `ValueError` for `days ∉ [1, 90]`.

#### Scenario: Default 30 days

- GIVEN `now_utc = 2026-06-11T12:00:00Z`
- WHEN `compute_backfill_dates(30, now_utc)`
- THEN returns list of 30 `date` objects, `[2026-05-13, ..., 2026-06-10]`

#### Scenario: Custom 5 days

- GIVEN `now_utc = 2026-06-11T12:00:00Z`
- WHEN `compute_backfill_dates(5, now_utc)`
- THEN returns `[2026-06-06, 2026-06-07, 2026-06-08, 2026-06-09, 2026-06-10]`

#### Scenario: days=0 rejected

- GIVEN `now_utc = 2026-06-11T12:00:00Z`
- WHEN `compute_backfill_dates(0, now_utc)`
- THEN raises `ValueError`

#### Scenario: days=91 rejected

- GIVEN `now_utc = 2026-06-11T12:00:00Z`
- WHEN `compute_backfill_dates(91, now_utc)`
- THEN raises `ValueError`

---

### Requirement: Daily Window Computation (Pure)

`compute_window_for_date(target_date, store_tz)` MUST convert store-local midnight→end-of-day to UTC via `zoneinfo.ZoneInfo`.

#### Scenario: Specific date in Buenos Aires

- GIVEN `target_date = date(2026, 6, 9)` and `store_tz = ZoneInfo("America/Argentina/Buenos_Aires")`
- WHEN `compute_window_for_date(...)`
- THEN returns `(datetime(2026,6,9,3,0,0,tzinfo=UTC), datetime(2026,6,10,2,59,59,999999,tzinfo=UTC))`

---

### Requirement: T-1 Window Regression

`compute_t1_window(store_tz, now_utc)` MUST delegate to `compute_window_for_date` with `target_date = (now_utc - 1 day).date()`.

#### Scenario: T-1 calls through to compute_window_for_date

- GIVEN `now_utc = datetime(2026,6,11,12,0,0,tzinfo=UTC)` and `store_tz = ZoneInfo("America/Bogota")`
- WHEN `compute_t1_window(store_tz, now_utc)`
- THEN returns same as `compute_window_for_date(date(2026,6,10), store_tz)`

---

### Requirement: Backfill Loop Iteration

`run_bronze_with_backfill(ctx, backfill_days)` MUST iterate `compute_backfill_dates()`, calling `run_bronze_impl` per date with fresh per-iteration `run_id` (uuid4), `run_timestamp_utc`, and `target_date`. Each iteration is independent. MUST return `0` if all SUCCESS, `1` if any FAILED.

#### Scenario: One log row per iteration day

- GIVEN `backfill_days=3`, all iterations succeed
- WHEN the wrapper runs
- THEN `logs` receives 3 rows, each with distinct `run_id` and `target_date` reflected in S3 partitions

#### Scenario: Fail-soft continues on iteration failure

- GIVEN iteration 2 raises `OtterAPIError`
- WHEN the wrapper catches the exception
- THEN iteration 3 still executes; 2 SUCCESS + 1 FAILED log rows; CLI exits non-zero

#### Scenario: Without backfill unchanged (T-1)

- GIVEN `backfill=False`
- WHEN `run_bronze_impl` is invoked
- THEN exactly 1 log row written; T-1 window computed; no iteration

---

### Requirement: Click CLI — Backfill Flags

The `run-bronze` command MUST accept `--backfill/--no-backfill` (default `--no-backfill`) and `--backfill-days N` (`click.IntRange(1, 90)`, default 30).

#### Scenario: --backfill-days 0 rejected by Click

- GIVEN CLI invocation `--backfill --backfill-days 0`
- WHEN Click parses the flag
- THEN exits non-zero before any pipeline code runs

#### Scenario: --backfill-days 91 rejected by Click

- GIVEN CLI invocation `--backfill --backfill-days 91`
- WHEN Click parses the flag
- THEN exits non-zero before any pipeline code runs

---

## MODIFIED Requirements — Bronze Ingestion (SCN-014)

### Requirement: Bronze S3 Path Correctness (SCN-014 delta)

The system MUST write to `s3://.../merchant_id={id}/year=YYYY/month=MM/day=DD/{endpoint}-{run_timestamp_utc}.json`. Partition (`year/month/day`) MUST reflect `target_date` (order/ingestion date). Filename timestamp MUST reflect `run_timestamp_utc` (run instant). `build_bronze_key` signature becomes `(merchant_id, endpoint, target_date, run_timestamp_utc) -> str`. `target_date` is REQUIRED (no default).

(Previously: partition and filename both derived from `run_timestamp_utc`.)

#### Scenario: target_date determines Hive partition

- GIVEN `target_date = date(2026,6,9)`, `run_timestamp_utc = datetime(2026,6,10,2,5,0,tzinfo=UTC)`
- WHEN `build_bronze_key("M1", "orders", target_date, run_timestamp_utc)`
- THEN partition is `year=2026/month=06/day=09` (not day=10)

#### Scenario: run_timestamp determines filename only

- GIVEN `target_date = date(2026,6,9)`, `run_timestamp_utc = datetime(2026,6,10,2,5,0,tzinfo=UTC)`
- WHEN key is built
- THEN filename contains `20260610T020500Z` (run time), partition is day=09

#### Scenario: Re-run same target_date yields same partition, distinct filename

- GIVEN same `target_date=date(2026,6,9)` but different `run_timestamp_utc` values (run A @ 02:05Z, run B @ 14:30Z)
- WHEN both keys are built
- THEN both share partition `day=09`; filenames differ by timestamp; distinct S3 objects coexist under same partition

---

## REMOVED Requirements

None.

---

## Scenario-to-Test Mapping

| # | Scenario | Test File |
|---|----------|-----------|
| 1 | Default 30 days | `test_run.py::test_compute_backfill_dates_default_30` |
| 2 | Custom 5 days | `test_run.py::test_compute_backfill_dates_custom_5` |
| 3 | days=0 rejected | `test_run.py::test_compute_backfill_dates_zero_rejected` |
| 4 | days=91 rejected | `test_run.py::test_compute_backfill_dates_over_cap_rejected` |
| 5 | compute_window_for_date | `test_run.py::test_compute_window_for_date_buenos_aires` |
| 6 | T-1 calls through | `test_run.py::test_compute_t1_window_delegates_to_window_for_date` |
| 7-9 | SCN-014 delta (3) | `test_bronze_keys.py::test_target_date_determines_partition` + 2 |
| 10 | One log row per day | `test_run.py::test_backfill_writes_one_log_row_per_day` |
| 11 | Fail-soft continues | `test_run.py::test_backfill_fail_soft_continues_on_error` |
| 12 | Without backfill unchanged | `test_run.py::test_backfill_false_no_iteration` |
| 13 | --backfill-days 0 rejected | `test_run.py::test_cli_backfill_days_zero_rejected` |
| 14 | --backfill-days 91 rejected | `test_run.py::test_cli_backfill_days_over_cap_rejected` |
