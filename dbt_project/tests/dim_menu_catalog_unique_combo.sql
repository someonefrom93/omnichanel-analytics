/*
  Singular test: dim_menu_catalog MUST have unique (merchant_id, line_item_sku).
  Returns zero rows when the constraint is satisfied.
  FAILURE (any rows returned) = duplicate combos exist — violates the
  incremental+merge unique_key contract.
*/

select
    merchant_id,
    line_item_sku,
    count(*) as duplicate_count
from {{ ref('dim_menu_catalog') }}
group by 1, 2
having count(*) > 1
