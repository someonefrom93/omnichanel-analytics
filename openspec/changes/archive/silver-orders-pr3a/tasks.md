# Tasks: silver-orders-pr3a

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~323 |
| Estimated file count | 11 |
| Estimated test count | 8 (1 unit + 1 integration + 6 dbt tests) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR (PR3a is already a slice of umbrella PR3; PR3b is separate sdd-new cycle) |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Phase 1: Foundation — pyproject + uv sync

- [x] 1.1 **Add dbt deps** — Add `dbt-core>=1.8,<2.0` + `dbt-duckdb>=1.8,<2.0` to `[project] dependencies` in `pyproject.toml`. Run `uv sync`. Verify `dbt --version`. Files: `pyproject.toml`. Spec: ADDED §dbt Project Setup. *Done when: `uv sync` succeeds, `dbt --version` ≥ 1.8.*

## Phase 2: dbt Project Skeleton + Profiles

- [x] 2.1 **Create dbt_project.yml + profiles.yml** — `dbt_project.yml`: name=`ofae_analytics`, profile=`ofae_analytics`, model-paths, incremental defaults, Parquet format, vars block. `profiles.yml`: `dev` target (local DuckDB + mirror path) and `prod` target (S3 httpfs + secrets from env). Files: `dbt_project/dbt_project.yml`, `dbt_project/profiles.yml`. Design: §dbt Project Layout, §profiles.yml. *Done when: `dbt debug --target dev` succeeds.*

## Phase 3: Source Definition

- [x] 3.1 **Create _sources.yml** — Define `bronze.orders` source with `external_location` using `read_json_auto(..., format='array')` pointing to Bronze glob. Files: `dbt_project/models/silver/_sources.yml`. Spec: ADDED §bronze.orders Source. Design: §Source Definition. *Done when: `dbt compile` resolves source.*

## Phase 4: parse_bronze_filename Macro

- [x] 4.1 **Create macro** — DuckDB regex extracting `target_date` (YYYYMMDD→YYYY-MM-DD) + `run_timestamp_utc` from `_filename`. Files: `dbt_project/macros/parse_bronze_filename.sql`. Design: §Macro. *Done when: macro compiles via `dbt parse`.*

## Phase 5: silver_orders Model + Schema + Tests

- [ ] 5.1 **Write silver_orders.sql** — CTE: `orders` unnest → `items` unnest → select 13 columns snake_case. `is_incremental()` filter on `created_at`. Config: `materialized='incremental'`, `unique_key=['order_id','source_marketplace']`. Files: `dbt_project/models/silver/silver_orders.sql`. Spec: ADDED §§Materialization, Column Contract. Design: §Model SQL Logic. *Done when: `dbt run --select silver_orders --target dev` materializes.*

- [ ] 5.2 **Write silver_orders.yml** — 13 columns with types + descriptions. `not_null` tests on `order_id`, `source_marketplace`, `total_amount`. Composite `unique` on `(order_id, source_marketplace)`. Files: `dbt_project/models/silver/silver_orders.yml`. Spec: ADDED §dbt Tests. Design: §Schema File. *Done when: `dbt test --select silver_orders` passes.*

- [ ] 5.3 **Write custom test** — `silver_orders_not_null_revenue.sql`: `SELECT * WHERE total_amount IS NULL`. Files: `dbt_project/tests/silver_orders_not_null_revenue.sql`. Spec: ADDED §Null total_amount. Design: §Custom Data Test. *Done when: test passes on valid data; fails on injected null.*

## Phase 6: Unit Test — dbt Project Config Guard

- [ ] 6.1 **Parse dbt_project.yml** — Load YAML, assert `name`, `profile`, model materialization defaults, `model-paths` include `models/silver/`. Files: `tests/unit/transformation/test_dbt_project_yml.py`. Design: §Unit Test. *Done when: `pytest tests/unit/transformation/` green.*

## Phase 7: Integration Test — dbtRunner + moto S3

- [ ] 7.1 **Write integration test** — moto S3 fixture + `orders_response.json` seed. Temp DuckDB + profiles.yml pointing to moto URL. `dbtRunner().invoke(['build', ...])`. Assert Parquet exists, row count = 2, columns match spec. Mark `@pytest.mark.integration`. Files: `tests/integration/test_dbt_silver_orders.py`. Spec: ADDED §End-to-End. Design: §Pytest Integration Harness. *Done when: `pytest -m integration tests/integration/test_dbt_silver_orders.py` green.*

## Phase 8: Polish

- [ ] 8.1 **Update README** — Add "Silver Transformation" subsection with setup, `dbt build`, local mirror instructions. Files: `README.md`. *Done when: Silver section present, commands documented.*

- [ ] 8.2 **Update .env.example** — Add `OMCAE_DBT_TARGET`, `OMCAE_S3_BUCKET_BRONZE`, `OMCAE_S3_BUCKET_SILVER`. Files: `.env.example`. *Done when: new env vars listed with defaults.*

- [ ] 8.3 **Lint + type check** — `uv run ruff check`, `uv run mypy src/`, `uv run pytest -m "not integration"`. Files: all. *Done when: all gates green.*
