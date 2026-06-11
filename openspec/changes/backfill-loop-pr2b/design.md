# Design: Backfill Loop (PR2b)

> References: `spec.md` (14 scenarios), `openspec/specs/bronze-ingestion/spec.md` (SCN-014 baseline).

## Locked Decisions (from proposal)

| Fork | Choice | Rationale |
|------|--------|-----------|
| Partition key | `target_date` on `build_bronze_key` (SCN-014) | Umbrella locks "order date for partition, run timestamp for filename" |
| Fail semantics | Fail-soft per iteration; CLI exits non-zero on any FAILED | User spec |
| Validation | Both Click `IntRange(1,90)` AND Python `ValueError` | Defence-in-depth |
| Per-iteration run_id | `run_id_override` kwarg on `run_bronze_impl` | Pure function stays pure; deterministic tests |

## Module Layout

Only 4 production files touched. No new files.

```
src/omc_analytics/
├── common/config.py        (+6)  backfill + backfill_days fields
├── ingestion/bronze_keys.py (+10) target_date param
├── ingestion/bronze_writer.py (+10) forward target_date
└── ingestion/run.py        (+110) helpers + wrapper + Click options
```

## Interfaces / Contracts

### `compute_backfill_dates(days: int, now_utc: datetime) -> list[date]`

Pure. Oldest-first, ending yesterday. Formula: `[(now_utc.date() - timedelta(days=i)) for i in range(days, 0, -1)]`. Raises `ValueError` for `days < 1 or days > 90`.

### `compute_window_for_date(target_date: date, store_tz: ZoneInfo) -> tuple[datetime, datetime]`

Pure. Converts `target_date` at store-local midnight → UTC start; `target_date` at 23:59:59.999999 local → UTC end. Uses `zoneinfo.ZoneInfo`.

### `compute_t1_window` refactor

```python
def compute_t1_window(store_tz, now_utc):
    target_date = (now_utc - timedelta(days=1)).date()
    return compute_window_for_date(target_date, store_tz)
```

### `build_bronze_key` (SCN-014 delta)

```python
def build_bronze_key(
    merchant_id: str,
    endpoint: str,
    target_date: date,           # NEW, required
    run_timestamp_utc: datetime,
) -> str:
```

Partition: `year={target_date.year}/month={target_date.month:02d}/day={target_date.day:02d}`.
Filename: `{endpoint}-{run_timestamp_utc.strftime("%Y%m%dT%H%M%SZ")}.json`.

### `BronzeWriter.write_raw` delta

Signature: `write_raw(merchant_id, endpoint, payload, target_date, run_timestamp_utc) -> str`. Forwards `target_date` to `build_bronze_key`.

### `run_bronze_impl` extension

New kwargs: `run_id_override: UUID | None = None`, `run_timestamp_override: datetime | None = None`, `target_date: date | None = None`. When `target_date is None`, T-1 path unchanged. When set, uses explicit date for window + bronze keys. Internally: `run_ctx.run_id` / `run_ctx.run_timestamp_utc` are swapped if overrides present.

### `run_bronze_with_backfill(ctx: RunContext, backfill_days: int) -> int`

Wrapper for the loop:
```python
dates = compute_backfill_dates(backfill_days, datetime.now(UTC))
failed = False
store_tz = ZoneInfo(creds.store_tz)
for target_date in dates:
    iteration_run_id = uuid4()
    iteration_run_ts = datetime.now(UTC)
    try:
        run_bronze_impl(ctx, run_id_override=iteration_run_id,
                        run_timestamp_override=iteration_run_ts,
                        target_date=target_date)
    except Exception:
        failed = True
        # FAILED log already inserted by run_bronze_impl's except block
        continue
return 1 if failed else 0
```

### `RunContext` delta

Two new fields: `backfill: bool = False`, `backfill_days: int = 30`.

### Click CLI delta

```python
@click.option("--backfill/--no-backfill", default=False)
@click.option("--backfill-days", type=click.IntRange(1, 90), default=30)
```

`_build_deps` gains `backfill` + `backfill_days` kwargs, forwards them into `RunContext`. CLI wires: if `backfill` → `run_bronze_with_backfill(...)`; else → `run_bronze_impl(...)`.

## Data Flow (Backfill Path)

```
CLI: --backfill --backfill-days 7
  → _build_deps(backfill=True, backfill_days=7)
  → run_bronze_with_backfill(ctx, 7)
    → compute_backfill_dates(7, now_utc) → [D-7, ..., D-1]
    → for target_date in dates:
        run_id = uuid4()
        run_ts = now_utc()
        run_bronze_impl(ctx, run_id_override=run_id, target_date=target_date)
          → compute_window_for_date(target_date, store_tz)
          → fetch orders → write_raw(..., target_date=target_date, run_timestamp_utc=run_ts)
          → S3: .../day=DD/orders-{run_ts}.json  (DD = target_date.day)
          → ... (reports same pattern)
          → logs.insert_started / update_finished per iteration
```

## Test Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | `compute_backfill_dates` | 4 parametrized cases; pure, no mocks |
| Unit | `compute_window_for_date` | 1 case with ZoneInfo; pure |
| Unit | `compute_t1_window` regression | 1 case; assert delegates to `compute_window_for_date` |
| Unit | `build_bronze_key` SCN-014 delta | 3 new tests for partition/filename contract; 9 existing updated (mechanical: add `target_date=run_ts.date()`) |
| Unit | `BronzeWriter.write_raw` delta | 1-2 tests updated to pass `target_date` |
| Unit | `run_bronze_with_backfill` | 3 tests (happy path, fail-soft, no-backfill regression); mock `run_bronze_impl` |
| Unit | Click flags | 2 tests via `CliRunner`; assert non-zero exit for 0/91 |
| Integration | None new (PR2b is pure orchestration; S3 integration covered by PR1) |

**Strict TDD flow**: RED (write failing test) → GREEN (minimal impl) → REFACTOR. Per `config.yaml` `apply.tdd: true`.

## Risks

| Risk | Mitigation |
|------|------------|
| 30× loop exceeds Otter rate limits | Serial (locked); PR1's 3-retry 429 backoff per iteration |
| 9 existing `test_bronze_keys.py` tests break on new signature | Mechanical update: `target_date=run_ts.date()` reproduces old partition for T-1 |
| `_build_deps` already overwrites CLI pre-built `RunContext` | `_build_deps` gains `backfill` + `backfill_days` kwargs (confirmed in code: line 436 overwrites) |
| Re-runs create N timestamped objects per partition | README documents; Silver (PR3) picks latest by filename lexicographic order |
