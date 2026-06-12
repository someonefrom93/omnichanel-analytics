# Delta Spec: silver-reports-pr3b

> PR3b adds `silver_reports` model, `dbt_runner` Python wrapper, `omc-ingest run-silver`
> CLI subcommand. Baseline: `openspec/specs/silver-orders-pr3a/spec.md`,
> `openspec/specs/bronze-ingestion/spec.md`. No behavioral change to Bronze writers.

## ADDED Requirements — Silver Transformation (PR3b)

### Requirement: bronze.reports_enqueue and bronze.reports_result Source Definitions
The system MUST extend `_sources.yml` with two new `bronze` source tables, each with a
per-table `external_location` glob matching their respective filename patterns.

#### Scenario: reports_enqueue source resolves
- GIVEN `OMCAE_BRONZE_PATH` is set to the Bronze base path
- WHEN `dbt compile --select source:bronze.reports_enqueue` runs
- THEN the source resolves via `read_json_auto` targeting `reports_enqueue-*.json`

#### Scenario: reports_result source resolves
- GIVEN `OMCAE_BRONZE_PATH` is set to the Bronze base path
- WHEN `dbt compile --select source:bronze.reports_result` runs
- THEN the source resolves via `read_json_auto` targeting `reports_result-*.json`

### Requirement: silver_reports Materialization
The system MUST materialize `silver_reports` as `incremental+merge` with scalar
`unique_key='job_id'`, producing one Parquet row per Otter async report job. The model
MUST join `bronze.reports_enqueue` and `bronze.reports_result` by the `jobId` field
(internally cast to `job_id`), matching each enqueue to its result payload.

#### Scenario: One row per job_id from matching jobId values
- GIVEN Bronze holds a `reports_enqueue-*.json` row with `jobId=job_abc123` and
  a `reports_result-*.json` row with the same `jobId=job_abc123`
- WHEN `dbt run --select silver_reports` executes
- THEN the Silver table has exactly 1 row with `job_id='job_abc123'`

#### Scenario: Re-run is idempotent
- GIVEN `silver_reports` already contains `job_id='job_abc123'`
- WHEN the same Bronze data is re-run
- THEN `job_abc123` is merge-updated in place and no duplicate rows exist

### Requirement: silver_reports Column Contract
The model MUST output 12 columns: `job_id`, `merchant_id`, `report_date`, `enqueue_at`,
`enqueue_status`, `result_status`, `result_period_start`, `result_period_end`,
`gross_sales_amount`, `gross_sales_currency`, `net_payout_amount`,
`net_payout_currency`. All amounts SHALL be BIGINT in minor currency units; currency
codes SHALL be `VARCHAR(3)`.

#### Scenario: All 12 columns present with correct types
- GIVEN `dbt build` completes for `silver_reports`
- WHEN the Parquet output is queried
- THEN all 12 columns exist with snake_case names
- AND `gross_sales_amount` is typed as BIGINT
- AND `net_payout_currency` is typed as VARCHAR

### Requirement: dbt Tests on silver_reports
The system MUST run `not_null` on `job_id`, `merchant_id`, `report_date`, `enqueue_at`,
`result_status`, `gross_sales_amount`, `net_payout_amount`; `unique` on `job_id`; and a
custom singular test asserting 0 rows where `result_status='WARN'`.

#### Scenario: All tests pass on valid data
- GIVEN `silver_reports` materialized from the reports fixtures
- WHEN `dbt test --select silver_reports` runs
- THEN all `not_null`, `unique`, and custom tests exit 0

#### Scenario: WARN status causes test failure
- GIVEN a Bronze result where `status='WARN'`
- WHEN `dbt test` runs the custom `silver_reports_no_warn_status` test
- THEN the test fails (hard stop; Silver flags, doesn't default)

### Requirement: dbt_runner Python Wrapper
The system MUST provide `src/omc_analytics/transformation/dbt_runner.py` — a wrapper
around `dbtRunner` that resolves `--project-dir` and `--profiles-dir`, accepts a
`LogsPort`, and writes `STARTED` → `SUCCESS`/`FAILED` rows.

#### Scenario: STARTED row written before dbt invocation
- GIVEN an `InMemoryLogs` instance
- WHEN `dbt_runner.run_silver(logs, select='silver_reports')` is called
- THEN a `STARTED` log row exists before dbt executes

#### Scenario: SUCCESS row written on dbt exit 0
- GIVEN dbt build succeeds
- WHEN `run_silver` completes
- THEN the log row transitions to `SUCCESS` with `error_class=NULL`

#### Scenario: FAILED row on dbt exception
- GIVEN dbt raises an exception
- WHEN `run_silver` catches it
- THEN the log row shows `FAILED` with `error_class` from the exception
- AND the exception is re-raised

### Requirement: omc-ingest run-silver CLI
The system MUST expose a Click `silver` sub-group attached to the existing `cli` group
in `src/omc_analytics/ingestion/run.py`, with a `run-silver` command accepting
`--merchant-id`, `--env` (default `dev`, choices `["dev","staging","prod"]`), and
optional `--select`.

#### Scenario: Successful invocation exits 0
- GIVEN valid dbt project and temp DuckDB
- WHEN `omc-ingest run-silver --merchant-id M1 --env dev` is invoked
- THEN exit code is 0 and a `SUCCESS` log row is written

#### Scenario: dbt failure exits non-zero
- GIVEN dbt build fails
- WHEN `run-silver` is invoked
- THEN exit code is non-zero and a `FAILED` log row is written

### Requirement: silver_reports Integration Test
A pytest integration test MUST run `dbt build --select +silver_reports` via
`dbtRunner` in-process against moto S3, asserting Parquet row count and column types.

#### Scenario: Integration test asserts row count and columns
- GIVEN moto S3 seeded with `reports_enqueue_response.json` and
  `reports_result_ready.json`
- WHEN `dbtRunner` invokes `dbt build` in-process
- THEN the Silver table has 1 row with `job_id='job_abc123'`
- AND `gross_sales_amount=12500`, `net_payout_amount=8750`

## MODIFIED Requirements — Bronze Ingestion

### Requirement: Reports Bronze Path Contract (Silver-side)
(Previously: SCN-014 defined the `build_bronze_key` for reports writes only.)

The Bronze path contract for `reports_enqueue-{ts}.json` and `reports_result-{ts}.json`
is now consumed downstream by dbt sources. The join in `silver_reports` uses the
`jobId` field from both sources to match enqueue to result.

#### Scenario: dbt source globs match reports patterns
- GIVEN the extended `_sources.yml` with per-table globs
- WHEN Bronze writes `reports_enqueue-20260610T120000Z.json` and
  `reports_result-20260610T120000Z.json`
- THEN both dbt sources resolve without error

## MODIFIED Requirements — Local Test Mocking

### Requirement: dbtRunner Wrapper as Reusable Test Seam
(Previously: `dbtRunner` was exercised only inside the PR3a integration test.)

The `dbt_runner` module SHALL serve as a reusable, mockable seam for all dbt
invocations. Unit tests MAY substitute a mock `dbtRunner` to assert the LogsPort
lifecycle (STARTED → SUCCESS/FAILED) without running dbt.

#### Scenario: Unit test mocks dbtRunner, asserts log lifecycle
- GIVEN a mock `dbtRunner` returning `dbtRunnerResult(success=True, exception=None)`
- WHEN `dbt_runner.run(logs, ..., select='silver_reports')` is called
- THEN the log store contains STARTED → SUCCESS rows
- AND the mock was invoked with the expected arguments
