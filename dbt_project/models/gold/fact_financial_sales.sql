{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['merchant_id', 'order_id', 'source_marketplace', 'line_item_sku'],
        on_schema_change='append_new_columns',
        file_format='parquet',
    )
}}

/*
  fact_financial_sales: Gold fact table — one row per order line item with
  computed margin.

  Sources:
    - silver_orders (Silver line-item model from PR3a)
    - merchant_cogs_seed (stub COGS seed; PR5 swaps to real PostgreSQL table)

  Margin arithmetic:
    gross_order_value             = silver_orders.total_amount
    estimated_marketplace_commission = gross × {{ var('commission_rate', 0.15) }}
    calculated_recipe_cogs        = merchant_cogs_seed.recipe_cost   (0 if absent)
    packaging_cost                = merchant_cogs_seed.packaging_cost (0 if absent)
    true_net_payout_margin        = gross − commission − cogs − packaging

  LEFT JOIN on COGS — missing SKU yields zero costs, not dropped rows.

  Incremental: merge on 4-column composite PK. Re-runs are idempotent.
*/

with orders as (
    select * from {{ ref('silver_orders') }}
),

cogs as (
    select * from {{ ref('merchant_cogs_seed') }}
    {# PR5: swap to ref('merchant_cogs') (real PostgreSQL table) #}
)

select
    o.merchant_id,
    o.order_id,
    o.source_marketplace,
    o.line_item_sku,
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
