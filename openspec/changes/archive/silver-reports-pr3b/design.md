# Design: silver-reports-pr3b

## Technical Approach

Extend PR3a's dbt project with `silver_reports` — a two-CTE model joining Bronze
`reports_enqueue` and `reports_result` by `run_timestamp_utc` extracted from
filename via the existing `parse_bronze_filename` macro. Add a `dbt_runner` Python
wrapper for in-process `dbtRunner` invocation with LogsPort lifecycle tracking.
Wire a Click `silver` sub-group with `run-silver` command into the existing `cli`.

All 6 design forks resolved in the proposal. This design executes them.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Two-source join | 1 model, two CTEs | 2 staging models | DuckDB `read_json_auto` cheap; extra dbt models = extra build+test steps |
| Join key | Filename `run_timestamp_utc` | `jobId` field, partition path | Both files share same timestamp suffix per PR1 invariant; reliable |
| Per-table `external_location` | Table-level meta in `_sources.yml` | Separate sources, single glob | Table-level scoping isolates globs; keeps `bronze` source name flat |
| `dbtRunner` wrapper | `transformation/dbt_runner.py` module | Direct call in CLI, deprecated `dbt.cli.main` | Testable in isolation; CLI stays thin |
| Click subcommand location | `silver` sub-group attached to `cli` | New entrypoint, inline in `run.py` | Isolates Silver wiring in `transformation/cli.py`; keeps `omc-ingest` surface |
| dbt log streaming | `logging.Handler` context manager + post-run summary | `callbacks=[]`, subprocess stdout | Plugs into stdlib; dbt log lines go to same Python logger |

## Data Flow

```
bronze.reports_enqueue ──┐
  (filename→ts, jobId)    │
                          ├─ JOIN ON run_timestamp_utc ──→ silver_reports (Parquet)
bronze.reports_result  ──┘     (11 columns, incremental+merge, unique_key=job_id)
  (filename→ts, totals)
                               │
                               ▼
                    dbt_runner.run_silver()
                      │
                      ├─ LogsPort.insert_started(STARTED)
                      ├─ dbtRunner.invoke(['build','--select','+silver_reports'])
                      └─ LogsPort.update_finished(SUCCESS|FAILED)
```

## Source Definitions — Extension

Two new tables under `bronze` source in `_sources.yml`, each with table-level `meta.external_location`:

```yaml
- name: reports_enqueue
  meta:
    external_location: "read_json_auto('{{ env_var('OMCAE_BRONZE_PATH') }}/.../reports_enqueue-*.json', format='auto')"
- name: reports_result
  meta:
    external_location: "read_json_auto('{{ env_var('OMCAE_BRONZE_PATH') }}/.../reports_result-*.json', format='auto')"
```

## `silver_reports` SQL Logic

1. **Config**: `{{ config(materialized='incremental', unique_key='job_id') }}`
2. **CTE `enqueue`**: `SELECT ... FROM {{ source('bronze','reports_enqueue') }}`, parse `_filename` via macro → `run_timestamp_utc`, extract `jobId` → `job_id`
3. **CTE `result`**: Same source + macro, extract `status`, `period_start/end`, `totals.gross_sales/net_payout`
4. **Final SELECT**: `enqueue LEFT JOIN result USING (run_timestamp_utc)`, 11 typed columns
5. **Incremental filter**: `{% if is_incremental() %} WHERE run_timestamp_utc > (SELECT MAX(enqueue_at) FROM {{ this }}) {% endif %}`

## `dbt_runner` Wrapper

`src/omc_analytics/transformation/dbt_runner.py` (~50 LOC):

```python
class dbt_runner:
    def __init__(self, logs: LogsPort, project_dir: Path, profiles_dir: Path):
        ...
    def run(self, *, select: str, merchant_id: str, env: str, run_id: UUID | None = None) -> bool:
        # 1. Insert STARTED log row
        # 2. dbtRunner().invoke(['build', '--select', select, ...])
        # 3. On success: update_finished(SUCCESS); return True
        # 4. On exception: update_finished(FAILED, error_class, error_message); re-raise
```

`LogsPort` row uses `pipeline_name='otter_silver_transformation'` (extending the `RunLog` literal type).

## Click CLI — `omc-ingest run-silver`

`src/omc_analytics/transformation/cli.py` (~40 LOC):

```python
@click.group(name="silver")
def silver_group(): ...

@silver_group.command("run-silver")
@click.option("--merchant-id", required=True)
@click.option("--env", required=True, type=click.Choice(["dev","staging","prod"]))
@click.option("--select", default="+silver_reports")
def run_silver(merchant_id, env, select): ...
```

Wired in `ingestion/run.py` via: `cli.add_command(transformation.cli.silver_group)`.

## File Changes

| File | Action | LOC |
|------|--------|-----|
| `dbt_project/models/silver/_sources.yml` | Modify | +18 |
| `dbt_project/models/silver/silver_reports.sql` | New | 75 |
| `dbt_project/models/silver/silver_reports.yml` | New | 35 |
| `dbt_project/tests/silver_reports_unique_job_id.sql` | New | 6 |
| `dbt_project/tests/silver_reports_no_warn_status.sql` | New | 6 |
| `src/omc_analytics/transformation/__init__.py` | Modify | +3 |
| `src/omc_analytics/transformation/dbt_runner.py` | New | 50 |
| `src/omc_analytics/transformation/cli.py` | New | 40 |
| `src/omc_analytics/ingestion/run.py` | Modify | +6 |
| `tests/integration/test_dbt_silver_reports.py` | New | 55 |
| `tests/unit/transformation/test_dbt_runner.py` | New | 25 |
| `tests/unit/transformation/test_silver_cli.py` | New | 15 |
| `Makefile` | Modify | +4 |
| `README.md` | Modify | +10 |

**Total: ~348 LOC** (within 400-line cap).

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| dbt tests | `not_null`, `unique`, WARN-status guard | YAML schema + singular SQL tests |
| Unit | `dbt_runner` lifecycle | Mock `dbtRunner`, assert STARTED→SUCCESS/FAILED |
| Unit | CLI rendering | `CliRunner`, assert command invokes wrapper |
| Integration | Full `dbt build` against moto S3 | Follow PR3a pattern: moto S3 fixture + `dbtRunner` + DuckDB query assertions |

## Locked Decisions

| Fork | Decision |
|------|----------|
| Two-source join shape | 1 model, two CTEs (Option A) |
| Filename-based join key | `regexp_extract` from `_filename` (Option A) |
| Incremental strategy | `merge`, `unique_key='job_id'` (Option C) |
| `dbtRunner` integration | `dbt_runner.py` wrapper module (Option B) |
| Click subcommand location | `silver` sub-group attached to `cli` (Option C) |
| dbt log streaming | `logging.Handler` + post-run summary (Option B+C) |
| Sourcing two files | Two table-level `external_location` blocks (Option A) |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `_filename` virtual column not available in DuckDB `read_json_auto` | Low | Verified in PR3a macro tests; integration test asserts |
| `jobId` field missing from result fixture | Low | Join uses `run_timestamp_utc`, not `jobId` |
| `dbtRunner` handler leaks across invocations | Low | Context manager in `finally`; unit test asserts handler count |
| CLI registration breaks existing `run-bronze` | Low | Additive `cli.add_command`; integration test runs both |

## Out of Scope

PII salting, Gold star-schema, COGS, UI, OAuth authorization_code, webhooks, cron.
