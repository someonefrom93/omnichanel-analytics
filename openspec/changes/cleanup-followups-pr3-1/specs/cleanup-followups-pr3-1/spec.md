# Delta for Cleanup Follow-ups (PR3.1)

> Test/doc follow-ups closing WARNINGs from PR2a, PR2b, PR3a. No production behavior change.

## ADDED Requirements

### Requirement: PostgresLogs Error-Path Test Coverage
The test suite MUST exercise `update_finished` and `_acquire` exception paths to lift `postgres_logs.py` coverage ≥ 80%.

#### Scenario: update_finished wraps psycopg2.Error as PostgresLogsError
- GIVEN a mocked PostgresLogs pool whose cursor.execute raises `psycopg2.Error`
- WHEN `update_finished(run_id, "SUCCESS", None, None)` is called
- THEN `PostgresLogsError` is raised wrapping the psycopg2.Error
- AND `putconn` is called exactly once (finally-block guarantee)

#### Scenario: _acquire releases connection when cursor raises on insert
- GIVEN a mocked pool whose getconn returns a connection that raises `psycopg2.Error` on cursor()
- WHEN `insert_started(RunLog(...))` is called via `_acquire()`
- THEN the exception propagates
- AND `putconn` is called exactly once (finally-block guarantee)

### Requirement: run_bronze_with_backfill Exit Code Contract
The docstring of `run_bronze_with_backfill` MUST explicitly name `sys.exit(return_code)` as the propagation mechanism.

#### Scenario: Docstring names sys.exit propagation
- GIVEN the source file `src/omc_analytics/ingestion/run.py`
- WHEN `run_bronze_with_backfill` docstring is read
- THEN it states the CLI handler calls `sys.exit(return_code)` (line ~618)
- AND the docstring retains the existing fail-soft and return-code semantics

### Requirement: silver_orders Idempotency Under Re-run
An integration test MUST run `dbt build --select silver_orders` twice against the same seed and assert row count is invariant.

#### Scenario: Two consecutive dbt builds produce identical row count
- GIVEN moto S3 seeded with `orders_response.json` fixture and DuckDB pre-seeded with `bronze.orders`
- WHEN `dbt build --select silver_orders` runs a first time
- AND `dbt build --select silver_orders` runs a second time against the same database
- THEN `SELECT COUNT(*) FROM silver_orders` returns the same value after both runs
