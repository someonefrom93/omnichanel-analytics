# Delta Spec: pii-salted-pr4a

> PR4a adds salted PII hashing to `silver_orders`. Baseline:
> `openspec/specs/silver-orders-pr3a/spec.md`.

## ADDED Requirements — PII Masking

### Requirement: MerchantCredentials.pii_salt Field
`MerchantCredentials` MUST include an optional `pii_salt: str | None` field.
A Pydantic validator SHALL auto-generate a UUID4 hex string on first save
if the field is absent (`None` or missing). Once set, the salt is immutable
(validated on load — mismatch raises `ValidationError`).

#### Scenario: Auto-generated on first save with no salt
- GIVEN `MerchantCredentials(merchant_id="M1", ...)` without `pii_salt`
- WHEN the model is constructed
- THEN `pii_salt` is a 32-char hex string (UUID4, no hyphens)

#### Scenario: Preserved on round-trip through KMS
- GIVEN creds with `pii_salt="abc123"`
- WHEN saved to and loaded from KMSSecrets
- THEN `pii_salt` matches `"abc123"` exactly

#### Scenario: Immutable after first set
- GIVEN creds with `pii_salt="abc123"`
- WHEN attempting `creds.model_copy(update={"pii_salt": "xyz"})` on a frozen model
- THEN a new instance is created; the original is unchanged

### Requirement: salted_hash dbt Macro
The system MUST provide a `salted_hash` dbt macro at
`dbt_project/macros/salted_hash.sql`. It SHALL take two args:
`column_name` (the raw hash column) and `salt_var` (default `'pii_salt'`).
It SHALL compile to `hash({{ var(salt_var) }} || {{ column_name }})`
using DuckDB `hash()` (xxhash64).

#### Scenario: Macro compiles with default salt var
- GIVEN `dbt_project.yml` defines `vars.pii_salt: "test-salt"`
- WHEN `dbt compile` runs against a model calling `{{ salted_hash("customer_name_hash") }}`
- THEN the compiled SQL contains `hash('test-salt' || customer_name_hash)`

#### Scenario: Custom salt_var compiles correctly
- GIVEN `dbt_project.yml` defines `vars.merchant_salt: "m1-salt"`
- WHEN a model calls `{{ salted_hash("col", salt_var='merchant_salt') }}`
- THEN the compiled SQL contains `hash('m1-salt' || col)`

### Requirement: New Salted Columns on silver_orders
`silver_orders` MUST output two new columns: `customer_name_hash_salted` and
`customer_phone_hash_salted`. Raw `customer_name_hash` and `customer_phone_hash`
columns SHALL be preserved (back-compat). The salted columns SHALL use the
`salted_hash` macro.

#### Scenario: Output includes 4 PII columns
- GIVEN `dbt build --select silver_orders` completes
- WHEN `DESCRIBE silver_orders` is queried
- THEN `customer_name_hash`, `customer_phone_hash` exist (raw)
- AND `customer_name_hash_salted`, `customer_phone_hash_salted` exist (salted)

#### Scenario: Salted hash is deterministic
- GIVEN `OMCAE_PII_SALT="fixed-salt"`
- WHEN two dbt builds run with identical Bronze data
- THEN salted columns produce identical values across runs

### Requirement: not_null Tests on Salted Columns
dbt schema tests MUST assert `not_null` on `customer_name_hash_salted` and
`customer_phone_hash_salted` in `silver_orders.yml`.

#### Scenario: not_null tests pass on valid data
- GIVEN valid Bronze source with non-null PII fields
- WHEN `dbt test --select silver_orders` runs
- THEN `not_null` tests on both salted columns pass (exit 0)

### Requirement: salted_hash Stability Singular Test
A custom singular test `silver_orders_salted_hash_stable.sql` MUST assert
that re-materializing the same Bronze data yields identical salted hashes
(checks `COUNT(*) WHERE hash differs` = 0).

#### Scenario: Stability test passes on idempotent data
- GIVEN silver_orders materialized once
- WHEN the stability test runs after a second `dbt run`
- THEN zero rows are returned (all salted hashes match)

### Requirement: OMCAE_PII_SALT Build-Time Env Var
The system MUST read the salt from `OMCAE_PII_SALT` env var at dbt build time
via `var('pii_salt')`. `.env.example` SHALL document the variable.
`dbt_project.yml` SHALL declare `vars.pii_salt: "{{ env_var('OMCAE_PII_SALT') }}"`.

#### Scenario: Missing env var fails at parse time
- GIVEN `OMCAE_PII_SALT` is unset
- WHEN `dbt parse` runs
- THEN it fails with a clear error referencing the missing env var

#### Scenario: Env var documented in .env.example
- GIVEN `.env.example`
- WHEN read
- THEN a line for `OMCAE_PII_SALT` exists with description

## MODIFIED Requirements — Silver Orders

### Requirement: silver_orders Column Contract
(Previously: 13 columns; now 15 with 2 salted PII columns added. Raw hash
columns preserved.)

The model MUST output: `order_id`, `source_marketplace`, `merchant_id`,
`target_date`, `run_timestamp_utc`, `created_at`, `total_amount`,
`total_currency`, `line_item_sku`, `line_item_name`, `line_item_qty`,
`line_item_unit_price`, `line_item_unit_currency`,
`customer_name_hash` (raw), `customer_phone_hash` (raw),
`customer_name_hash_salted` (salted), `customer_phone_hash_salted` (salted).

#### Scenario: All 15 columns present with snake_case names
- GIVEN `dbt build` completes for `silver_orders`
- WHEN the Parquet output is queried
- THEN all 15 columns exist with snake_case names

### Requirement: dbt Tests on silver_orders
(Previously: `not_null` on `order_id`, `source_marketplace`, `total_amount`
plus composite `unique`. Now adds `not_null` on both salted columns.)

#### Scenario: All built-in tests pass on valid fixture data
- GIVEN `silver_orders` materialized from the PR1 fixture
- WHEN `dbt test --select silver_orders` runs
- THEN all `not_null` (including 2 salted columns) and `unique` tests exit 0

## Deviations

- **Hash primitive**: DuckDB `hash()` (xxhash64) instead of PRD §3.2 "SHA-256".
  Per-merchant stable non-reversible ID goal is met. PR5+ may swap to DuckDB
  SHA-256 extension if compliance demands.
