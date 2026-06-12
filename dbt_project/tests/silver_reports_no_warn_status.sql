{{ config(severity='warn') }}
/* Warn if any silver_reports row has result_status='WARN' (admin anomaly review). */
select job_id, merchant_id, result_status from {{ ref('silver_reports') }} where result_status = 'WARN'