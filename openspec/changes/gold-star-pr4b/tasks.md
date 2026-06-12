# Tasks: gold-star-pr4b

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~253 LOC |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Phase 1: merchant_cogs Seed + Schema

- [x] 1.1 Create `dbt_project/seeds/merchant_cogs_seed.csv` — 6 rows covering store_001 (4 SKUs) + store_002 (2 SKUs)
- [x] 1.2 Create `dbt_project/seeds/_seeds.yml` — declare columns `merchant_id`, `line_item_sku`, `recipe_cost`, `packaging_cost` with `not_null` on merchant_id + line_item_sku

## Phase 2: dim_menu_catalog Model + Schema + Tests

- [x] 2.1 Create `dbt_project/models/gold/dim_menu_catalog.sql` — incremental+merge, unique_key=['merchant_id','line_item_sku'], SELECT DISTINCT with GROUP BY 1,2, source `{{ ref('silver_orders') }}`
- [x] 2.2 Create `dbt_project/models/gold/dim_menu_catalog.yml` — document 5 columns + `not_null` on merchant_id, line_item_sku
- [x] 2.3 Create `dbt_project/tests/dim_menu_catalog_unique_combo.sql` — singular test: COUNT(*) GROUP BY 1,2 HAVING COUNT(*) > 1 → 0 rows

## Phase 3: fact_financial_sales Model + Schema + Tests + Config

- [x] 3.1 Create `dbt_project/models/gold/fact_financial_sales.sql` — incremental+merge, unique_key=['merchant_id','order_id','source_marketplace','line_item_sku'], LEFT JOIN merchant_cogs_seed, margin arithmetic
- [x] 3.2 Create `dbt_project/models/gold/fact_financial_sales.yml` — document 10 columns + `not_null` on 4 PK columns
- [x] 3.3 Add `vars.commission_rate: 0.15` to `dbt_project/dbt_project.yml`

## Phase 4: Integration Test + dbt build End-to-End

- [x] 4.1 Create `tests/integration/test_dbt_gold_star_schema.py` — mirror test_dbt_silver_orders_e2e.py pattern, dbt build seed→dim→fact→tests, assert row counts and margin values
- [x] 4.2 Run full suite: `uv run ruff check && uv run mypy src/omc_analytics && OMCAE_PII_SALT=test-salt uv run dbt compile --project-dir dbt_project && uv run pytest -x -m integration`
