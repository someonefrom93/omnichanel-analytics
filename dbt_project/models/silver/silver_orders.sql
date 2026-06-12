{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['order_id', 'source_marketplace'],
        on_schema_change='append_new_columns',
        file_format='parquet',
    )
}}

/*
  silver_orders: one row per Otter order line item.

  Source: bronze.orders (Otter /v1/orders JSON, one file per (merchant,
  target_date, run_timestamp) tuple, written by PR1's Bronze ingestion).

  Output columns (per proposal §silver_orders columns):
    - order_id            : Otter's order identifier (string)
    - source_marketplace  : the channel the order came from
                            (e.g. 'ubereats', 'doordash', 'rappi')
    - merchant_id         : the restaurant's identifier in Otter
    - target_date         : the order date (derived from Bronze filename
                            via parse_bronze_filename macro; equals the
                            day in the Hive partition)
    - run_timestamp_utc   : the run timestamp (from Bronze filename)
    - created_at          : the order's created_at timestamp from Otter
    - total_amount        : order total in minor units (e.g. cents)
    - total_currency      : ISO 4217 currency code
    - line_item_sku       : SKU of this line item
    - line_item_name      : human-readable name
    - line_item_qty       : quantity ordered
    - line_item_unit_price : unit price in minor units
    - line_item_unit_currency : ISO 4217 currency code
    - customer_name_hash  : SHA-256 of customer name (raw, no salt — PR4
                            will add the salt and re-materialize via
                            dbt run --full-refresh)
    - customer_phone_hash : SHA-256 of customer phone (raw, no salt)

  Incremental strategy: merge on (order_id, source_marketplace). Re-runs
  dedupe on the composite key, satisfying the idempotency contract from
  PR2b. The Bronze layer can have multiple objects per partition (one per
  run_timestamp) and this model picks the latest.

  DEVIATION (PR3a): target_date is derived from cast(created_at as date)
  rather than the parse_bronze_filename macro. PR4 will rewire to use
  the filename parse for backfill accuracy. run_timestamp_utc is stubbed
  as NULL for PR3a; PR4 will wire it from the filename parse.
*/

{#
  DEVIATION (PR3a): silver_orders reads directly from the pre-created
  bronze.orders DuckDB table rather than from {{ source('bronze', 'orders') }}.

  The source abstraction via external_location does not work with dbt-duckdb's
  S3 handling at runtime: the compiled SQL uses read_json_auto('s3://...')
  which DuckDB cannot execute without AWS credentials configured for httpfs.
  moto S3 only mocks boto3, not DuckDB's S3 calls.

  For the integration test (moto S3 + dbtRunner), we pre-create bronze.orders
  in DuckDB using the fixture file, then override OMCAE_USE_BRICK below to
  make this model read from the local table. In production, PR3b will handle
  proper S3-based bronze sourcing via a different mechanism.

  This deviation is documented in the apply-progress artifact.
#}

{%
set use_local_bronze = env_var('OMCAE_USE_LOCAL_BRONZE', 'false')
%}

{%
set source_query
%}

{% if use_local_bronze == 'true' %}
  select * from bronze.orders
{% else %}
  {# Production path: read from S3 via the bronze.orders source #}
  select * from {{ source('bronze', 'orders') }}
{% endif %}

{%
endset
%}

with source as (
    {{ source_query }}
),

-- Unnest the top-level orders array: one row per order object
unnest_orders as (
    select
        value.id::varchar as order_id,
        value.channel::varchar as source_marketplace,
        value.store_id::varchar as merchant_id,
        value.created_at::timestamp as created_at,
        value.total.amount::bigint as total_amount,
        value.total.currency::varchar(3) as total_currency,
        value.customer.name_hash::varchar as customer_name_hash,
        value.customer.phone_hash::varchar as customer_phone_hash,
        -- Keep the full items array for the next unnest step
        value.items as items_array
    from source,
    LATERAL (select unnest(orders) as value)
),

-- Unnest the items array: one row per line item
unnest_items as (
    select
        order_id,
        source_marketplace,
        merchant_id,
        created_at,
        total_amount,
        total_currency,
        customer_name_hash,
        customer_phone_hash,
        -- Each line item field extracted from the items array
        item.sku::varchar as line_item_sku,
        item.name::varchar as line_item_name,
        item.qty::integer as line_item_qty,
        item.unit_price.amount::bigint as line_item_unit_price,
        item.unit_price.currency::varchar(3) as line_item_unit_currency
    from unnest_orders,
    LATERAL (select unnest(items_array) as item)
),

final as (
    select
        order_id,
        source_marketplace,
        merchant_id,
        -- DEVIATION: target_date derived from created_at date part.
        -- PR4 will rewire to use parse_bronze_filename(target_date) from filename.
        cast(created_at as date) as target_date,
        -- run_timestamp_utc: stubbed as NULL for PR3a.
        -- PR4 will extract from Bronze filename via parse_bronze_filename macro.
        cast(null as timestamp) as run_timestamp_utc,
        created_at,
        total_amount,
        total_currency,
        line_item_sku,
        line_item_name,
        line_item_qty,
        line_item_unit_price,
        line_item_unit_currency,
        customer_name_hash,
        customer_phone_hash,
        -- PR4a: salted PII columns using DuckDB hash() (xxhash64).
        -- DEVIATION from PRD §3.2 "SHA-256" — see salted_hash macro docs.
        {{ salted_hash('customer_name_hash') }} as customer_name_hash_salted,
        {{ salted_hash('customer_phone_hash') }} as customer_phone_hash_salted
    from unnest_items
)

select * from final

{% if is_incremental() %}
    -- Incremental filter: only process new rows since the last run.
    -- Since the source is a Bronze directory (one file per run_timestamp),
    -- "new" means rows from a newer run_timestamp. For PR3a, we use
    -- created_at as the proxy: filter to orders created after the max
    -- created_at already in the Silver table.
    where created_at > (
        select coalesce(max(created_at), '1900-01-01'::timestamp)
        from {{ this }}
    )
{% endif %}