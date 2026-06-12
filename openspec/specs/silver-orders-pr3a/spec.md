# Delta Spec: silver-orders-pr3a

> PR3a adds the Silver dbt transformation layer: dbt project setup + `silver_orders`
> model. Baseline: `openspec/specs/bronze-ingestion/spec.md`. PR3a does NOT modify
> Bronze behavior; it documents the S3 path contract consumed downstream by dbt and
> adds integration-test coverage for the dbt build pipeline.

## ADDED Requirements — Silver Transformation

### Requirement: dbt Project Setup
The system MUST provide a valid dbt project at `dbt_project/` with `dbt parse` exiting 0.

#### Scenario: Project parses cleanly
- GIVEN `dbt_project/dbt_project.yml` and `profiles.yml` exist
- WHEN `dbt parse` runs
- THEN exit code is 0

### Requirement: bronze.orders Source Definition
The system MUST define a `bronze.orders` dbt source reading `read_json_auto(...)` from
`otter/merchant_id=*/year=*/month=*/day=*/orders-*.json`.

#### Scenario: Source resolves in dev target (local mirror)
- GIVEN `OMCAE_DBT_TARGET=dev` and a pre-seeded local mirror directory
- WHEN `dbt compile --select source:bronze.orders` runs
- THEN the source resolves without error

#### Scenario: Source resolves in prod target (S3 httpfs)
- GIVEN `OMCAE_DBT_TARGET=prod` and valid AWS credentials
- WHEN `dbt compile --select source:bronze.orders` runs
- THEN the source resolves via DuckDB `httpfs` from the Bronze S3 bucket

### Requirement: silver_orders Materialization
The system MUST materialize `silver_orders` as `incremental+merge` with composite
`unique_key=['order_id','source_marketplace']`, producing one Parquet row per line item.

#### Scenario: New orders are merged, one row per line item
- GIVEN Bronze source has 2 orders (ord_001 with 1 item, ord_002 with 1 item)
- WHEN `dbt run --select silver_orders` executes
- THEN the Silver Parquet has exactly 2 rows

#### Scenario: Re-run is idempotent (no duplicates)
- GIVEN `silver_orders` already contains ord_001
- WHEN the same Bronze data is re-run
- THEN ord_001 is merge-updated in place and no duplicate rows exist

### Requirement: silver_orders Column Contract
The model MUST output: `order_id`, `source_marketplace`, `merchant_id`,
`created_at`, `total_amount`, `total_currency`, `line_item_sku`, `line_item_name`,
`line_item_qty`, `line_item_unit_price`, `line_item_unit_currency`,
`customer_name_hash` (raw copy, NOT salted), `customer_phone_hash` (raw copy, NOT salted),
`customer_name_hash_salted` (PR4a salted), `customer_phone_hash_salted` (PR4a salted).
(Previously: 13 columns, no salted PII columns.)

#### Scenario: All 15 columns present with snake_case names
- GIVEN `dbt build` completes for `silver_orders`
- WHEN the Parquet output is queried
- THEN all 15 columns exist with snake_case names
- AND `customer_name_hash` matches the source `customer.name_hash` byte-for-byte
- AND `customer_name_hash_salted` and `customer_phone_hash_salted` are non-null

### Requirement: dbt Tests on silver_orders
The system MUST run `not_null` on `order_id`, `source_marketplace`, `total_amount`,
`customer_name_hash_salted`, `customer_phone_hash_salted` and `unique` composite on
`(order_id, source_marketplace)`. (Previously: only `order_id`, `source_marketplace`,
`total_amount` had not_null; PR4a adds salted columns.)

#### Scenario: All built-in tests pass on valid fixture data
- GIVEN `silver_orders` materialized from the PR1 `orders_response.json` fixture
- WHEN `dbt test --select silver_orders` runs
- THEN all `not_null` (including 2 salted columns) and composite `unique` tests exit 0

#### Scenario: Null total_amount causes hard failure
- GIVEN a Bronze order where `total.amount` is null
- WHEN `dbt test` runs the custom `silver_orders_not_null_revenue` test
- THEN the test fails (hard stop; 0.00-default + anomaly flag deferred to PR4 Gold)

### Requirement: End-to-End dbt Build Integration Test
A pytest integration test (`-m integration`) MUST run `dbt build` via `dbtRunner`
in-process against moto S3 and assert the Silver Parquet output shape.

#### Scenario: Integration test asserts row count and shape
- GIVEN moto S3 seeded with `orders_response.json` at the Bronze path
- WHEN `dbtRunner` invokes `dbt build` in-process
- THEN the Silver Parquet file exists at the configured path
- AND the row count matches the Bronze source line-item count
- AND no real AWS credentials or network calls are used

### Requirement: dbt Profile Target Selection
The system MUST select the dbt profile target via `OMCAE_DBT_TARGET` env var
(`dev` → local mirror, `prod` → S3 direct via httpfs).

#### Scenario: dev target selects local mirror
- GIVEN `OMCAE_DBT_TARGET=dev`
- WHEN `dbt run` executes
- THEN DuckDB reads from the local mirror path

#### Scenario: prod target selects S3 direct
- GIVEN `OMCAE_DBT_TARGET=prod`
- WHEN `dbt run` executes
- THEN DuckDB reads from S3 via `httpfs` using env-provided credentials

## MODIFIED Requirements — Bronze Ingestion

### Requirement: Bronze S3 Path Contract as Downstream Interface
(Previously: SCN-014 defined the `build_bronze_key` format for writes only.)

The Bronze path contract `otter/merchant_id={id}/year=YYYY/month=MM/day=DD/orders-{run_timestamp}.json`
is now consumed downstream by the dbt source `bronze.orders`. No behavioral change to Bronze
writers. This is a documented interface between medallion layers.

#### Scenario: dbt source glob matches Bronze key pattern
- GIVEN the `_sources.yml` `external_location` glob
- WHEN Bronze writes `orders-20260610T120000Z.json` under `merchant_id=M1/year=2026/month=06/day=09/`
- THEN `dbt compile` resolves the source without error

## MODIFIED Requirements — Local Test Mocking

### Requirement: dbt Integration Test Harness
(Previously: the test stack used `responses` + `moto[s3]` for HTTP and S3 mocking only.)

The test stack MUST now include `dbtRunner` invoked in-process against moto S3,
exercising the full `dbt build` pipeline. Opt-in via `pytest -m integration`.

#### Scenario: dbt build runs against moto S3 in-process
- GIVEN `tests/integration/test_dbt_silver_orders.py`
- WHEN `pytest -m integration` runs
- THEN `dbtRunner` invokes `dbt build`, Parquet is materialized, and assertions pass
- AND no real AWS credentials or network calls are used
