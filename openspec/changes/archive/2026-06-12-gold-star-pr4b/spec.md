# Spec: gold-star-schema (PR4b)

> New capability. Source: umbrella `openspec/changes/pii-gold-pr4/proposal.md`.

## Purpose

Define Gold star schema models (`dim_menu_catalog`, `fact_financial_sales`) and the
`merchant_cogs` stub seed that feed PR5's Streamlit analytics UI.

## Requirements

### Requirement: dim_menu_catalog Materialization

The system MUST materialize `dim_menu_catalog` as `incremental+merge` with composite
`unique_key=['merchant_id', 'line_item_sku']`. Columns: `merchant_id`, `line_item_sku`,
`line_item_name`, `first_seen_at`, `last_seen_at`. Source: `{{ ref('silver_orders') }}`.

#### Scenario: One row per SKU per merchant

- GIVEN `silver_orders` has 3 orders with SKUs BURGER_CLASSIC (×2) and FRIES_MEDIUM (×1) for store_001
- WHEN `dbt run --select dim_menu_catalog` executes
- THEN `dim_menu_catalog` has 2 rows — one per unique (merchant_id, line_item_sku) combo

#### Scenario: Re-run is idempotent (no duplicates)

- GIVEN `dim_menu_catalog` already has (store_001, BURGER_CLASSIC)
- WHEN same Bronze data is rebuilt
- THEN row count does NOT increase (merge dedupes on unique_key)

### Requirement: fact_financial_sales Materialization

The system MUST materialize `fact_financial_sales` as `incremental+merge` with composite
`unique_key=['merchant_id', 'order_id', 'source_marketplace', 'line_item_sku']`.
Columns: PK columns + `created_at`, `gross_order_value`, `estimated_marketplace_commission`,
`calculated_recipe_cogs`, `packaging_cost`, `true_net_payout_margin`.

#### Scenario: Margin arithmetic is correct

- GIVEN gross=2500, commission rate=0.15, recipe_cogs=800, packaging_cogs=100
- WHEN the model computes margin
- THEN `estimated_marketplace_commission` = 375 (2500×0.15)
- AND `true_net_payout_margin` = 2500 - 375 - 800 - 100 = 1225

#### Scenario: Commission rate is configurable via dbt var

- GIVEN `dbt_project.yml` sets `vars.commission_rate: 0.20`
- WHEN `dbt run` executes
- THEN `estimated_marketplace_commission` = gross × 0.20

### Requirement: merchant_cogs Seed

The system MUST provide a dbt seed CSV at `dbt_project/seeds/merchant_cogs_seed.csv` with
columns `merchant_id`, `line_item_sku`, `recipe_cost`, `packaging_cost`. A YAML schema
MUST declare `not_null` tests on `merchant_id` and `line_item_sku`.

#### Scenario: Seed is loadable via dbt seed

- GIVEN `merchant_cogs_seed.csv` with 6 rows
- WHEN `dbt seed --select merchant_cogs_seed` runs
- THEN the table materializes with 6 rows and declared column types

### Requirement: dbt Tests

dbt tests MUST assert: `not_null` on all 4 PK columns of `fact_financial_sales`; `unique`
on `(merchant_id, line_item_sku)` for `dim_menu_catalog` (singular test).

#### Scenario: not_null fails when PK column is null

- GIVEN a row in `fact_financial_sales` where `order_id` is NULL
- WHEN `dbt test --select fact_financial_sales` runs
- THEN the `not_null` test on `order_id` fails with exit ≠ 0

#### Scenario: dim_menu_catalog uniqueness test passes

- GIVEN `dim_menu_catalog` has no duplicate (merchant_id, line_item_sku) combos
- WHEN the singular uniqueness test runs
- THEN it returns 0 rows and exits 0

### Requirement: Configurable Defaults

`estimated_marketplace_commission` SHALL default to 15% via `var('commission_rate', 0.15)`.
The variable MUST be declared in `dbt_project.yml`. `calculated_recipe_cogs` and
`packaging_cost` SHALL default to 0 when `merchant_cogs` join misses.

#### Scenario: Missing COGS row yields zero costs

- GIVEN a line item SKU has no match in `merchant_cogs_seed`
- WHEN `fact_financial_sales` computes margin
- THEN `calculated_recipe_cogs` = 0, `packaging_cost` = 0
- AND `true_net_payout_margin` = gross - commission (cogs treated as absent)

### Requirement: Integration Test

A pytest integration test (`-m integration`) MUST run `dbt build` via dbtRunner in-process
against moto S3 + temp DuckDB, seeding `merchant_cogs_seed` and asserting Gold model row
counts and margin arithmetic.

#### Scenario: Gold integration test asserts margin correctness

- GIVEN moto S3 seeded with the PR1 fixture
- WHEN `dbt build` runs (seed + dim + fact + tests)
- THEN `dim_menu_catalog` has exactly 2 rows (BURGER_CLASSIC, FRIES_MEDIUM)
- AND `fact_financial_sales` has exactly 2 rows with non-null margin columns
