{{
    config(
        severity='error',
    )
}}

/*
  Composite uniqueness test: order_id + source_marketplace must be unique.

  Per PRD §5.3: "one row per (order_id, source_marketplace) tuple."
  This test fails (hard stop) if any duplicate composite key is found.

  Replaces dbt_utils.unique_combination_of_columns since dbt_utils is
  not pip-installable in this environment.
*/

with grouped as (
    select
        order_id,
        source_marketplace,
        count(*) as row_count
    from {{ ref('silver_orders') }}
    group by order_id, source_marketplace
),

duplicates as (
    select order_id, source_marketplace
    from grouped
    where row_count > 1
)

select
    s.order_id,
    s.source_marketplace,
    s.merchant_id,
    s.created_at
from {{ ref('silver_orders') }} s
inner join duplicates d
    on s.order_id = d.order_id
    and s.source_marketplace = d.source_marketplace
order by s.order_id, s.source_marketplace