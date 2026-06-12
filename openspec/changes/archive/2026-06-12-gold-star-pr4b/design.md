# Design: gold-star-pr4b

## Technical Approach

Build two Gold marts from `silver_orders`: `dim_menu_catalog` (SKU dimension, DISTINCT+GROUP BY) and `fact_financial_sales` (margin fact, LEFT JOIN `merchant_cogs_seed` + dim). Stub COGS as a dbt seed. All cross-model references use `{{ ref() }}`.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Cross-model refs | `{{ ref() }}` | `{{ source() }}` | Same dbt project; ref() enables DAG ordering and schema resolution |
| COGS source | dbt seed CSV (6 rows) | PostgreSQL table | PR5 ships the real table; seed mirrors PR3's local-bronze deviation pattern |
| COGS join | LEFT JOIN | INNER JOIN | Missing SKU → zero costs, not row drop |
| Commission | `var('commission_rate', 0.15)` | Hardcoded | PR5 UI will need per-merchant override; var() makes it configurable now |
| dim PK dedup | `SELECT DISTINCT ... GROUP BY 1,2` | Window function (ROW_NUMBER) | Simpler; GROUP BY 1,2 with MIN/MAX is sufficient for dimension build |
| Gold schema | Same DuckDB DB as Silver | Separate DB | Single DB keeps ref() simple; PR5 can redirect if needed |
| Gold `_sources.yml` | NOT created | Source YAML at gold/ | No S3 external sources in gold layer — all refs are internal |

## Data Flow

```
merchant_cogs_seed (CSV)
        │
        ▼
  dbt seed ──→ merchant_cogs (table)
                     │
silver_orders ──→ dim_menu_catalog ──┐    ┌── merchant_cogs (LEFT JOIN)
        │         (DISTINCT+GROUP)    │    │
        │                            ▼    ▼
        └──────────────────→ fact_financial_sales
                              (JOIN silver_orders
                               + dim_menu_catalog
                               + merchant_cogs)
                                     │
                                     ▼
                              margin = gross
                                     - commission (15% default)
                                     - recipe_cogs
                                     - packaging_cost
```

## File Changes

| File | Action | LOC |
|------|--------|-----|
| `dbt_project/seeds/merchant_cogs_seed.csv` | Create | 8 |
| `dbt_project/seeds/_seeds.yml` | Create | 15 |
| `dbt_project/models/gold/dim_menu_catalog.sql` | Create | 25 |
| `dbt_project/models/gold/dim_menu_catalog.yml` | Create | 20 |
| `dbt_project/models/gold/fact_financial_sales.sql` | Create | 35 |
| `dbt_project/models/gold/fact_financial_sales.yml` | Create | 25 |
| `dbt_project/tests/dim_menu_catalog_unique_combo.sql` | Create | 10 |
| `dbt_project/dbt_project.yml` | Modify | +5 |
| `tests/integration/test_dbt_gold_star_schema.py` | Create | 95 |
| `README.md` | Modify | +15 |

**Total: ~253 LOC** (under 320 forecast, under 400-line budget).

## Interfaces / Contracts

### dim_menu_catalog SQL skeleton
```sql
{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['merchant_id', 'line_item_sku'],
        on_schema_change='append_new_columns',
        file_format='parquet',
    )
}}

select distinct
    merchant_id,
    line_item_sku,
    min(line_item_name) as line_item_name,
    min(created_at) as first_seen_at,
    max(created_at) as last_seen_at
from {{ ref('silver_orders') }}
group by 1, 2
```

### fact_financial_sales SQL skeleton
```sql
{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['merchant_id', 'order_id', 'source_marketplace', 'line_item_sku'],
        on_schema_change='append_new_columns',
        file_format='parquet',
    )
}}

with orders as (
    select * from {{ ref('silver_orders') }}
),
cogs as (
    select * from {{ ref('merchant_cogs_seed') }}
    -- PR5: swap to {{ ref('merchant_cogs') }} (real PostgreSQL table)
)
select
    o.merchant_id, o.order_id, o.source_marketplace, o.line_item_sku,
    o.created_at,
    o.total_amount as gross_order_value,
    round(o.total_amount * {{ var('commission_rate', 0.15) }}) as estimated_marketplace_commission,
    coalesce(c.recipe_cost, 0) as calculated_recipe_cogs,
    coalesce(c.packaging_cost, 0) as packaging_cost,
    o.total_amount
      - round(o.total_amount * {{ var('commission_rate', 0.15) }})
      - coalesce(c.recipe_cost, 0)
      - coalesce(c.packaging_cost, 0)
    as true_net_payout_margin
from orders o
left join cogs c
    on o.merchant_id = c.merchant_id
    and o.line_item_sku = c.line_item_sku
```

### Seed CSV schema
```csv
merchant_id,line_item_sku,recipe_cost,packaging_cost
store_001,BURGER_CLASSIC,800,100
store_001,FRIES_MEDIUM,300,50
store_001,COLA_LARGE,150,30
store_001,SALAD_CAESAR,600,80
store_002,BURGER_CLASSIC,850,110
store_002,FRIES_LARGE,350,55
```

### dbt_project.yml delta
```yaml
vars:
  commission_rate: 0.15
```

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| dbt test | not_null on 4 PK cols | YAML schema test on fact_financial_sales |
| dbt test | unique on dim_menu_catalog PK | Singular test `dim_menu_catalog_unique_combo.sql` |
| Integration | dbt build with seed + dim + fact + tests | dbtRunner in-process, mirror test_dbt_silver_orders_e2e.py pattern |
| Integration | Margin arithmetic assertion | Query fact_financial_sales and verify margin = gross - commission - cogs |

## Migration

- First `dbt seed && dbt run --select dim_menu_catalog fact_financial_sales` creates gold tables from scratch.
- Incremental runs add new rows; merge dedupes on existing keys.
- Rollback: `dbt run-operation drop_schema --args '{schema: gold}'` drops gold schema; `dbt seed --full-refresh` resets seed.

## Open Questions

None — all design forks resolved in umbrella proposal.
