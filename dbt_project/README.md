# OFAE Analytics — dbt Silver Transformation

This is the **Silver** transformation layer of the OFAE medallion architecture.
It reads raw Bronze JSON from `otter/merchant_id=*/year=*/month=*/day=*/orders-*.json`
and materializes conformed Parquet tables via **dbt-core + dbt-duckdb**.

## Running

```bash
# Development (local DuckDB + Bronze mirror)
OMCAE_DBT_TARGET=dev uv run dbt build

# Production (S3 direct via httpfs + AWS credentials)
OMCAE_DBT_TARGET=prod uv run dbt build
```

## Model Layout

- `silver_orders` — flattens one row per line item from Bronze orders JSON.
  (PR3a: this model; PR3b adds `silver_reports`)

## Input / Output

| Layer | Location |
|-------|----------|
| **Bronze** (input) | `s3://ofae-data-lakehouse-bronze-{env}/otter/...` |
| **Silver** (output) | `s3://ofae-data-lakehouse-silver-{env}/silver/...` |

## Project structure

```
dbt_project/
├── dbt_project.yml     # project config + model defaults
├── profiles.yml        # dev / prod target profiles
├── models/silver/      # silver_orders + schema + tests
├── macros/             # shared Jinja macros
└── tests/              # custom dbt singular tests
```