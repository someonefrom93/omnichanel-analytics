# Proposal: PII Salted Masking + Gold Star Schema (PR4)

## Intent

PR4 closes the analytical core of OFAE: (a) replace the raw SHA-256 PII columns
in `silver_orders` with a **salted** hash that prevents cross-merchant
correlation attacks, and (b) build the **Gold star schema** (`fact_financial_sales`
+ `dim_menu_catalog`) with a stub COGS source so the Streamlit UI (PR5) has
analytical marts to query. Both pieces are deferred from PR3; both unlock
PRD §3.2 (Silver PII + Gold star schema) and PRD §6.3 (Chart 2 Menu Engineering
Matrix, Chart 1 Profit Leakage).

## Scope

### In Scope
- **`pii_salt` field on `MerchantCredentials`** (auto-generated on first save).
- **`salted_hash` dbt macro** — deterministic, parameterized on `var('merchant_salt')`.
- **New columns** `customer_name_hash_salted`, `customer_phone_hash_salted` in `silver_orders` (raw columns kept for back-compat).
- **`dim_menu_catalog`** — composite PK `(merchant_id, line_item_sku)`, incremental+merge.
- **`fact_financial_sales`** — composite PK `(merchant_id, order_id, source_marketplace, line_item_sku)`, joins Silver + dim + merchant_cogs.
- **`merchant_cogs` stub** — dbt seed CSV (one row per SKU with `recipe_cost_minor`, `packaging_cost_minor`).
- **Margin arithmetic** — `gross_order_value`, `estimated_marketplace_commission` (15% default, configurable via `var('default_commission_bps')`), `calculated_recipe_cogs`, `true_net_payout_margin`.
- **Pytest integration tests** for both layers (moto S3 + temp DuckDB + `dbt build`).

### Out of Scope
- Streamlit UI, COGS admin editor, OAuth `authorization_code`, webhooks, cron.
- Real PostgreSQL `merchant_cogs` table (PR5).
- Per-merchant salt runtime lookup (PR5 via `SecretsPort`); PR4 uses a build-time `OMCAE_PII_SALT` env var.
- DuckDB community SHA-256 extension; PR4 uses `xxhash64` (see Risks).

## Capabilities

### New Capabilities
- `pii-masking`: salted hash of customer PII columns in `silver_orders`.
- `gold-star-schema`: `fact_financial_sales` + `dim_menu_catalog` + stub `merchant_cogs`.

### Modified Capabilities
- `silver-orders-pr3a`: delta — add `customer_name_hash_salted` and `customer_phone_hash_salted` columns (raw columns preserved).
- `local-test-mocking`: delta — dbt build integration test now also exercises Gold models + `dbt seed` of `merchant_cogs_seed`.

## Approach

| Area | Choice | Rationale |
|---|---|---|
| Hash primitive | DuckDB `hash(salt \|\| column)` (xxhash64) | No extension; deterministic; meets security goal (per-merchant stable, non-reversible ID). PRD §3.2 deviation — see Risks. |
| Salt source | `var('merchant_salt')` from `OMCAE_PII_SALT` env var | Per-build single salt; per-merchant lookup deferred to PR5. |
| Salted column additivity | `on_schema_change='append_new_columns'` (already in `silver_orders.sql:6`) | Back-compat; raw hash columns preserved. |
| COGS stub | dbt seed CSV → `{{ ref('merchant_cogs_seed') }}` | Matches PR3's `OMCAE_USE_LOCAL_BRONZE` deviation pattern; production swap is a ref in PR5. |
| Composite PKs | List-form `unique_key` (proven in PR3) | dbt-duckdb 1.10.1 verified working for `silver_orders`. |
| PR split | PR4a (PII) + PR4b (Gold) | ~280 + ~320 LOC; each autonomous, reversible. |

## Affected Areas

### PR4a (PII salted masking) — ~280 LOC
| File | Action | LOC |
|---|---|---|
| `src/omc_analytics/common/models.py` | Modify — add `pii_salt: str \| None` | +6 |
| `dbt_project/macros/salted_hash.sql` | New | 15 |
| `dbt_project/models/silver/silver_orders.sql` | Modify — add salted columns | +20 |
| `dbt_project/models/silver/silver_orders.yml` | Modify — document salted columns | +15 |
| `dbt_project/tests/silver_orders_salted_hash_stable.sql` | New — determinism test | 20 |
| `dbt_project/dbt_project.yml` | Modify — add `merchant_salt` var | +5 |
| `tests/unit/common/test_models.py` | New — salt auto-generation | 40 |
| `tests/unit/common/test_kms_secrets.py` | Modify — round-trip with `pii_salt` | +20 |
| `tests/integration/test_dbt_pii_salted.py` | New | 80 |
| `README.md` | Modify | +20 |
| `.env.example` | Modify — `OMCAE_PII_SALT` | +5 |

### PR4b (Gold star schema) — ~320 LOC
| File | Action | LOC |
|---|---|---|
| `dbt_project/seeds/merchant_cogs_seed.csv` | New | 12 |
| `dbt_project/seeds/_seeds.yml` | New | 20 |
| `dbt_project/models/gold/_sources.yml` | New | 25 |
| `dbt_project/models/gold/dim_menu_catalog.sql` | New | 65 |
| `dbt_project/models/gold/dim_menu_catalog.yml` | New | 35 |
| `dbt_project/models/gold/fact_financial_sales.sql` | New | 90 |
| `dbt_project/models/gold/fact_financial_sales.yml` | New | 40 |
| `dbt_project/tests/dim_menu_catalog_unique_combo.sql` | New | 15 |
| `dbt_project/dbt_project.yml` | Modify — add `default_commission_bps` | +5 |
| `tests/integration/test_dbt_gold_star_schema.py` | New | 90 |
| `README.md` | Modify | +25 |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| xxhash64 deviates from PRD §3.2 "SHA-256" wording | Med | Documented in spec §Deviations; security goal (per-merchant stable, non-reversible ID) is met; PR5+ can swap to DuckDB SHA-256 extension if compliance demands. |
| Single `OMCAE_PII_SALT` is build-wide, not per-merchant | Med | Per-merchant salt via `SecretsPort` is PR5 concern; PR4 ships a stable single salt; gold `dim_menu_catalog` already partitions on `merchant_id` so leaks are scoped. |
| `fact_financial_sales` 4-key composite PK; any NULL breaks merge | Low | dbt `not_null` test on all 4 PK columns in yml. |
| No UI consumer → schema drift risk between PR4 and PR5 | Low | Column contract is part of the delta spec; `sdd-verify` enforces. |
| First `dbt run --select silver_orders` after PR4a needs `--full-refresh` | Low | Documented in PR4a README; merge filter on `created_at` doesn't re-hash existing rows. |

## Rollback Plan

1. Revert PR branch.
2. `dbt run --full-refresh --select silver_orders` to drop the salted columns (handled by `on_schema_change='append_new_columns'` when columns are removed from the model SQL).
3. `dbt run-operation drop_schema --args '{schema: gold}'` to drop the Gold schema.
4. Remove the `pii_salt` field from `MerchantCredentials`; existing encrypted blobs still deserialize (field is `Optional`).
5. No S3 cleanup required; no DB migration.

## Dependencies

- Existing: `dbt-core>=1.8,<2.0`, `dbt-duckdb>=1.8,<2.0`, `pydantic`, `cryptography`.
- New env var: `OMCAE_PII_SALT` (build-time salt; auto-generated if absent in dev).

## Success Criteria

### PR4a
- [ ] `pii_salt` field present on `MerchantCredentials`; auto-generated on save when absent.
- [ ] `silver_orders` Parquet has `customer_name_hash_salted` and `customer_phone_hash_salted` columns.
- [ ] Salted columns are deterministic: same salt + same input → same output.
- [ ] Raw `customer_name_hash` / `customer_phone_hash` columns preserved (back-compat).
- [ ] `pytest -m integration tests/integration/test_dbt_pii_salted.py` green.

### PR4b
- [ ] `dim_menu_catalog` materializes with composite PK `(merchant_id, line_item_sku)`.
- [ ] `fact_financial_sales` materializes with 4-key composite PK; `true_net_payout_margin` = gross - commission - cogs.
- [ ] `merchant_cogs_seed` is a dbt seed with `not_null` tests on PK.
- [ ] `pytest -m integration tests/integration/test_dbt_gold_star_schema.py` green.
- [ ] Both PRs under 400 LOC each.

## Review Budget

- **PR4a gross forecast: ~280 LOC** (under 400)
- **PR4b gross forecast: ~320 LOC** (under 400)
- **400-line budget risk: High for the umbrella (600 LOC combined); Low per slice**
- **Chained PRs recommended: Yes**
- **Decision needed before apply: Yes** — orchestrator surfaces the PR4a/PR4b split to user (per §E Review Workload Guard, `ask-on-risk` delivery strategy).
