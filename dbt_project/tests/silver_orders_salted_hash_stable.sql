{#
  silver_orders_salted_hash_stable: validates that salted PII hashes
  are present and non-null on every silver_orders row.

  This is a defensive test: if the salted columns are ever missing
  (e.g., due to a schema mismatch where append_new_columns didn't
  pick them up), this test fails.

  True idempotency across dbt runs is validated by the integration
  test (tests/integration/test_dbt_pii_salted.py).
#}

{{
    config(
        severity='error',
    )
}}

select
    order_id,
    source_marketplace,
    customer_name_hash_salted,
    customer_phone_hash_salted
from {{ ref('silver_orders') }}
where
    customer_name_hash_salted is null
    or customer_phone_hash_salted is null
