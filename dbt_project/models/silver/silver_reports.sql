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

  Two-CTE model joining bronze.reports_enqueue and bronze.reports_result
  by job_id. Per PRD §3.2, financial aggregates from the result payload
  surface here.

  Join strategy: enqueue LEFT JOIN result on job_id.
  Both sources expose jobId as a top-level field, making the join reliable.
  In production S3 paths, both files share the same run_timestamp_utc suffix
  per ingestion run (PRD SCN-014 invariant); the job_id join is the authoritative
  link.
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
        e.jobId as job_id,
        r.result.store_id as merchant_id,
        cast(r.result.period_start as date) as report_date,
        cast(e.created_at as timestamp) as enqueue_at,
        e.status as enqueue_status,
        r.status as result_status,
        r.result.period_start as result_period_start,
        r.result.period_end as result_period_end,
        r.result.totals.gross_sales.amount as gross_sales_amount,
        r.result.totals.gross_sales.currency as gross_sales_currency,
        r.result.totals.net_payout.amount as net_payout_amount,
        r.result.totals.net_payout.currency as net_payout_currency
    from enqueue e
    left join result r
        on e.jobId = r.jobId
)

select * from joined

{% if is_incremental() %}
    where job_id is not null
{% endif %}