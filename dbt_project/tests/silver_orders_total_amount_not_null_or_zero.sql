{{
    config(
        severity='warn',
    )
}}

/*
  Custom data test: warn if any row in silver_orders has total_amount = 0.

  Per PRD §5.3: "Detections default to 0.00 while flagging an administrative
  anomaly row." This test warns operators when total_amount = 0 so they can
  review for null-source anomalies. Severity=warn means it logs but does not
  fail the build.
*/

select
    order_id,
    source_marketplace,
    merchant_id,
    total_amount,
    total_currency,
    created_at
from {{ ref('silver_orders') }}
where total_amount = 0