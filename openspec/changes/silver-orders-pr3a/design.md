# Design: silver-orders-pr3a

## Technical Approach

Add `dbt-core>=1.8,<2.0` and `dbt-duckdb>=1.8,<2.0` to `pyproject.toml`. Create
`dbt_project/` with two profile targets: `dev` (local filesystem mirror) and `prod`
(S3 direct via DuckDB `httpfs`). Define `bronze.orders` source reading Otter JSON
from the Bronze path. Implement `silver_orders` model unnesting `orders[]` and
`items[]` arrays into one row per line item. Materialize as `incremental+merge` with
list-form composite `unique_key`. Ship dbt tests: `not_null` on required columns,
composite `unique`, and a custom singular test for the null-revenue policy. Add a
pytest integration test running `dbtRunner` in-process against moto S3.

All design forks were resolved in the umbrella proposal — this design executes them.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| dbt invocation | `dbtRunner` in-process (Python API) | `subprocess` | moto S3 `endpoint_url` only reachable in-process; PR3b CLI will reuse `dbtRunner` |
| Composite `unique_key` | List form `['order_id','source_marketplace']` | String `'order_id,source_marketplace'` | dbt-duckdb >=1.8 supports list; string deprecated in 1.9+ |
| Dev target | Local filesystem mirror (`data/bronze_mirror/`) | Always S3 | Hermetic CI; no AWS needed for dev |
| PII hashing | Raw copy of `customer.name_hash`, `customer.phone_hash` | Salted SHA-256 | Salt design is PR4 concern; raw copy keeps Silver stable |
| Macro scope | `parse_bronze_filename` extracts timestamp | None | Minimal utility; usable by future Silver models. Droppable if budget tightens. |

## dbt Project Layout

```
dbt_project/
├── dbt_project.yml
├── profiles.yml
├── models/
│   └── silver/
│       ├── _sources.yml              # bronze.orders source definition
│       ├── silver_orders.sql         # model SQL
│       └── silver_orders.yml         # column schema + dbt tests
├── macros/
│   └── parse_bronze_filename.sql     # filename → target_date, run_timestamp_utc
└── tests/
    └── silver_orders_not_null_revenue.sql  # custom data test
```

## dbt_project.yml (key settings)

```yaml
name: ofae_analytics
version: '1.0'
profile: ofae_analytics
model-paths: ["models"]
target-path: "target"
models:
  ofae_analytics:
    silver:
      +materialized: incremental
      +incremental_strategy: merge
      +file_format: parquet
vars:
  bronze_mirror_path: "data/bronze_mirror"
```

## profiles.yml — Dual Target

Target selected by `OMCAE_DBT_TARGET` (default: `dev`).

| Target | Type | Path | Extensions |
|--------|------|------|------------|
| `dev` | duckdb | `dbt_project/data/dev.duckdb` (local) | `httpfs`, `parquet` |
| `prod` | duckdb | `s3://` via `httpfs` | `httpfs`, `parquet` |

**prod secrets block**: reads `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`
from env; scoped to the Bronze bucket prefix.

**Env vars consumed**: `OMCAE_DBT_TARGET`, `OMCAE_S3_BUCKET_BRONZE`,
`OMCAE_S3_BUCKET_SILVER`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`.

## Source Definition (`_sources.yml`)

```yaml
sources:
  - name: bronze
    schema: main
    tables:
      - name: orders
        external_location: |
          read_json_auto(
            '{{ env_var("OMCAE_BRONZE_PATH",
               "data/bronze_mirror") }}/otter/merchant_id=*/*/*/*/orders-*.json',
            format='array'
          )
```

The Otter JSON shape is `{"orders": [{"id":"ord_001","channel":"ubereats",...,
"items":[{...}]}],"next_cursor":null}`. The model unnests `orders[]` → then `items[]`.
`format='array'` parses the top-level array directly.

## `silver_orders` Model — SQL Logic

1. **Source CTE**: `SELECT * FROM {{ source('bronze','orders') }}`
2. **Unnest orders**: `UNNEST(orders)` → one row per order object; extract `id`,
   `channel`, `store_id`, `created_at`, `total`, `customer`
3. **Unnest items**: `UNNEST(items)` → one row per line item; extract `sku`, `name`,
   `qty`, `unit_price`
4. **Select columns** (snake_case):
   `order_id`, `source_marketplace` (from `channel`), `merchant_id` (from `store_id`),
   `created_at`, `total_amount` (from `total.amount`), `total_currency`,
   `line_item_sku`, `line_item_name`, `line_item_qty`,
   `line_item_unit_price`, `line_item_unit_currency`,
   `customer_name_hash` (raw copy), `customer_phone_hash` (raw copy)
5. **Incremental filter**: in `is_incremental()` block:
   `WHERE created_at > (SELECT COALESCE(MAX(created_at), '1970-01-01') FROM {{ this }})`
6. **Config**: `{{ config(materialized='incremental', unique_key=['order_id','source_marketplace']) }}`

## Macro: `parse_bronze_filename.sql`

Uses DuckDB `regexp_extract` to pull `target_date` (YYYYMMDD → YYYY-MM-DD) and
`run_timestamp_utc` from the `_filename` virtual column. Available for Silver models
needing partition metadata. ~15 LOC.

## Schema File (`silver_orders.yml`)

13 columns with types and descriptions. Test block:

```yaml
tests:
  - dbt_utils.unique_combination_of_columns:
      combination_of_columns:
        - order_id
        - source_marketplace
columns:
  - name: order_id
    tests: [not_null]
  - name: source_marketplace
    tests: [not_null]
  - name: total_amount
    tests: [not_null]
```

## Custom Data Test: `silver_orders_not_null_revenue.sql`

```sql
SELECT * FROM {{ ref('silver_orders') }} WHERE total_amount IS NULL
```

Hard-fail: zero rows expected. The 0.00 default + anomaly flag policy lives in
PR4 Gold (PRD §5.3). Documented in spec and design.

## Pytest Integration Harness

`tests/integration/test_dbt_silver_orders.py` (~85 LOC):

- **Fixture**: moto S3 bucket with `orders_response.json` uploaded to full Bronze path.
- **Fixture**: temp `dbt_project/data/bronze_mirror/` mirror for dev target.
- **Fixture**: temp `profiles.yml` with DuckDB path.
- **Test**: `dbtRunner().invoke(['build', '--project-dir', ..., '--profiles-dir', ...])`
- **Assert**: exit 0, Parquet file at Silver path, `SELECT COUNT(*)` = 2,
  columns match spec.
- **Mark**: `@pytest.mark.integration`.

## Unit Test

`tests/unit/transformation/test_dbt_project_yml.py` (~20 LOC): Parse `dbt_project.yml`,
assert `name="ofae_analytics"`, `profile="ofae_analytics"`, model materialization
default is `incremental`. Cheap config-drift guard.

## File Changes

| File | Action | LOC |
|------|--------|-----|
| `pyproject.toml` | Modify | +4 |
| `dbt_project/dbt_project.yml` | New | 25 |
| `dbt_project/profiles.yml` | New | 30 |
| `dbt_project/models/silver/_sources.yml` | New | 20 |
| `dbt_project/models/silver/silver_orders.sql` | New | 60 |
| `dbt_project/models/silver/silver_orders.yml` | New | 30 |
| `dbt_project/macros/parse_bronze_filename.sql` | New | 15 |
| `dbt_project/tests/silver_orders_not_null_revenue.sql` | New | 8 |
| `tests/integration/test_dbt_silver_orders.py` | New | 85 |
| `tests/unit/transformation/test_dbt_project_yml.py` | New | 20 |
| `README.md` | Modify | +20 |
| `.env.example` | Modify | +6 |

**Total forecast: 323 LOC** (under 353 target, within 400-line cap).

## Locked Decisions (from umbrella proposal)

| Fork | Decision |
|------|----------|
| dbt data source | S3 direct (prod), local mirror (dev fallback) |
| Materialization | `incremental+merge` |
| Composite `unique_key` | List `['order_id','source_marketplace']` |
| PII masking | Raw copy in Silver; salt deferred to PR4 |
| PR scope | PR3a = dbt + `silver_orders` only; PR3b = `silver_reports` + CLI |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| dbt-duckdb version drift | Low | Pin `>=1.8,<2.0` in pyproject.toml |
| moto S3 not reachable from dbt | Low | Use `dbtRunner` in-process; shares moto URL |
| Composite `unique_key` list form unsupported | Low | Pinned >=1.8; integration test validates merge |
| Otter JSON `format='array'` mismatch | Med | Integration test seeds known fixture; failure is loud (compile error) |

## Out of Scope (PR3b and beyond)

`silver_reports`, dbt runner CLI subcommand, PII salted hashing, Gold star-schema,
COGS, UI, OAuth authorization_code, webhooks, cron scheduling.

## Open Questions

None — all blocking decisions resolved in umbrella proposal.
