{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['merchant_id', 'line_item_sku'],
        on_schema_change='append_new_columns',
        file_format='parquet',
    )
}}

/*
  dim_menu_catalog: SKU dimension — one row per unique (merchant_id, line_item_sku).

  Source: silver_orders (the Silver line-item model from PR3a).
  Dedup strategy: SELECT DISTINCT with GROUP BY on the composite key.
  MIN(line_item_name) picks the most common name; first_seen_at / last_seen_at
  track the time range each SKU has been observed.

  Incremental: merge on (merchant_id, line_item_sku). Re-runs update
  last_seen_at and are idempotent — no duplicate rows.
*/

select distinct
    merchant_id,
    line_item_sku,
    min(line_item_name) as line_item_name,
    min(created_at) as first_seen_at,
    max(created_at) as last_seen_at
from {{ ref('silver_orders') }}
group by 1, 2
