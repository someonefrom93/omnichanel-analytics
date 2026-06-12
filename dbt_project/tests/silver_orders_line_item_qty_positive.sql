{{
    config(
        severity='error',
    )
}}

/*
  Column constraint test: line_item_qty must be > 0.

  Per spec: line_item_qty is the quantity ordered and must be positive.
  Replaces dbt_utils.expression_is_true for line_item_qty > 0.
*/

select
    order_id,
    source_marketplace,
    line_item_qty
from {{ ref('silver_orders') }}
where line_item_qty <= 0