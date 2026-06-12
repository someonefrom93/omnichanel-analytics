{{
    config(
        severity='error',
    )
}}

/*
  Column constraint test: total_amount must be >= 0.

  Per spec: total_amount is in minor units (cents) and must be non-negative.
  Replaces dbt_utils.expression_is_true for total_amount >= 0.
*/

select
    order_id,
    source_marketplace,
    total_amount
from {{ ref('silver_orders') }}
where total_amount < 0