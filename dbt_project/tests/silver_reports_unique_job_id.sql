{{ config(severity='error') }}
/* Hard failure if any silver_reports row has a duplicate job_id (PRD §5.3 invariant). */
select
    job_id,
    count(*) as duplicate_count
from {{ ref('silver_reports') }}
group by job_id
having count(*) > 1
