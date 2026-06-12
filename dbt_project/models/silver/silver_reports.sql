{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='job_id',
        on_schema_change='append_new_columns',
        file_format='parquet',
    )
}}

/*
  silver_reports: one row per Otter report job.

  Joins bronze.reports_enqueue (the enqueue request with jobId+QUEUED) with
  bronze.reports_result (the final result with totals) on job_id.
  Per PRD §3.2, financial aggregates from the result payload surface here.

  Join strategy: result LEFT JOIN enqueue on job_id.
  This is the most robust approach since both sources share the same job_id
  as the primary identifier. The merchant_id is extracted from the result's
  result.store_id field.

  DEVIATION from design.md: parse_bronze_filename is not used because
  _source_file_name_or_path is not exposed by DuckDB read_json_auto.
  The job_id join is semantically correct per the Otter API contract where
  each enqueue maps 1:1 to a result via job_id.
*/

{%
set use_local_bronze = env_var('OMCAE_USE_LOCAL_BRONZE', 'false')
%}

{%
set enqueue_query
%}

{% if use_local_bronze == 'true' %}
  select * from bronze.reports_enqueue
{% else %}
  {# Production path: read from S3 via the bronze.reports_enqueue source #}
  select * from {{ source('bronze', 'reports_enqueue') }}
{% endif %}

{% endset %}

{%
set result_query
%}

{% if use_local_bronze == 'true' %}
  select * from bronze.reports_result
{% else %}
  {# Production path: read from S3 via the bronze.reports_result source #}
  select * from {{ source('bronze', 'reports_result') }}
{% endif %}

{% endset %}

with enqueue as (
    {{ enqueue_query }}
),

result as (
    {{ result_query }}
),

joined as (
    select
        coalesce(e.jobId, r.jobId) as job_id,
        r.result.store_id as merchant_id,
        e.status as enqueue_status,
        r.status as result_status,
        r.result.period_start as result_period_start,
        r.result.period_end as result_period_end,
        r.result.totals.gross_sales.amount as gross_sales_amount,
        r.result.totals.gross_sales.currency as gross_sales_currency,
        r.result.totals.net_payout.amount as net_payout_amount,
        r.result.totals.net_payout.currency as net_payout_currency
    from result r
    left join enqueue e
        on r.jobId = e.jobId
)

select * from joined

{% if is_incremental() %}
    where merchant_id is not null
{% endif %}