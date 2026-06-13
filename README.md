# omc-analytics

Bronze ingestion pipeline for Omnichannel Foodservice Analytics.
Built with Python 3.12, Click CLI, boto3, and pytest.

## PR1 — What Ships

- **CLI**: `omc-ingest run-bronze --merchant-id <id> --env dev|staging|prod`
- **Modules**: `OtterClient`, `OAuthRefresher`, `BronzeWriter`, `RetryPolicy`
- **Ports**: `SecretsPort`, `LogsPort` (PR1 stubs; PR2 swaps to KMS + Postgres)
- **Errors**: `OtterAPIError`, `BackoffExhaustedError`, `ReportJobFailedError`, `ReportJobCancelledError`, `ReportPollingExhaustedError`, `OAuthRefreshError`, `OAuthInitialTokenError`, `BronzeWriteError`
- **Fixtures**: 4 ReDoc-derived JSON fixtures under `tests/fixtures/otter/`
- **Tests**: 9 unit tests for orchestration logic, 3 integration tests (opt-in)

## PR2a — What Ships (KMSSecrets + PostgresLogs + Config Wiring)

- **KMSSecrets** adapter: envelope encryption (`kms.generate_data_key` + AES-256-GCM),
  Postgres blob store, per-merchant blast-radius isolation
- **PostgresLogs** adapter: `pipeline_execution_logs` DDL, `psycopg2` `ThreadedConnectionPool`,
  `insert_started`/`update_finished` per locked 9-column schema
- **SQLiteLogs** adapter: production-grade SQLite for local dev without Postgres
- **Config wiring**: `OMCAE_SECRETS_BACKEND`, `OMCAE_LOGS_BACKEND`, `OMCAE_KMS_KEY_ID`,
  `OMCAE_PG_DSN`, `OMCAE_AWS_REGION` env vars; `secrets_factory`/`logs_factory` pick the
  right impl; dev-mode fallback (KMSSecrets → InMemorySecrets when no AWS creds)
- **New errors**: `KMSKeyError`, `KMSDecryptError`, `MerchantBlobCorruptError`,
  `PostgresLogsError`, `ConfigError`
- **Tests**: 182 unit tests, 4 integration tests (opt-in, via `pytest -m integration`)

## Setup

```bash
uv sync
```

## Run

```bash
# Unit tests only (default — skips slow integration tests)
make test

# Run including integration tests
make test-integration

# Lint + type check + tests
make check

# Individual quality gates
make lint
make typecheck
make format

# CLI help
python -m omc_analytics.ingestion.run --help
```

## Local Dev Without AWS

By default, the CLI uses in-memory implementations that require no external services:

```bash
# No env vars needed — defaults to memory backends
omc-ingest run-bronze --merchant-id my-store --env dev
```

To use SQLite for logs (file-based, no Postgres required):

```bash
OMCAE_LOGS_BACKEND=sqlite omc-ingest run-bronze --merchant-id my-store --env dev
```

## Production Configuration

Set these environment variables before running the CLI in production:

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `OMCAE_SECRETS_BACKEND` | `memory` | No | Secrets backend: `memory` \| `kms` |
| `OMCAE_LOGS_BACKEND` | `memory` | No | Logs backend: `memory` \| `sqlite` \| `postgres` |
| `OMCAE_KMS_KEY_ID` | — | When `SECRETS_BACKEND=kms` | KMS CMK KeyId or ARN |
| `OMCAE_PG_DSN` | — | When `LOGS_BACKEND=postgres` | PostgreSQL connection DSN |
| `OMCAE_AWS_REGION` | `us-east-1` | No | AWS region for boto3 S3/KMS clients |
| `AWS_ACCESS_KEY_ID` | — | When `SECRETS_BACKEND=kms` | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | — | When `SECRETS_BACKEND=kms` | AWS secret key |

Example (KMS + Postgres production):

```bash
export OMCAE_SECRETS_BACKEND=kms
export OMCAE_KMS_KEY_ID=arn:aws:kms:us-east-1:123456789:key/mrk-xxxxx
export OMCAE_LOGS_BACKEND=postgres
export OMCAE_PG_DSN=postgresql://user:pass@pg.example.com:5432/omc_analytics
export AWS_ACCESS_KEY_ID=AKIAXXXX
export AWS_SECRET_ACCESS_KEY=xxxxx
omc-ingest run-bronze --merchant-id my-store --env prod
```

### Backfill

The `omc-ingest run-bronze` command supports a backfill mode that re-runs
the Bronze ingestion for the last N days, useful for populating dashboards
after onboarding a new tenant or recovering from a multi-day outage.

Flags:

- `--backfill / --no-backfill` (default `--no-backfill`): enable backfill mode.
- `--backfill-days N` (default 30, range 1-90): how many days to backfill.

Examples:

```bash
# Re-run the last 7 days of Bronze ingestion for a merchant
omc-ingest run-bronze --merchant-id M1 --env prod --backfill --backfill-days 7

# Default behavior (single T-1 run)
omc-ingest run-bronze --merchant-id M1 --env prod
```

**Idempotency contract**: backfill iterations partition by **order date**
(so the S3 path `otter/merchant_id={id}/year=YYYY/month=MM/day=DD/` reflects
the data, not the run time). Filenames use the run timestamp. Re-running
the same backfill date creates multiple timestamped objects under the
same partition; the Silver tier (PR3, upcoming) will pick the latest
when materializing.

**Fail-soft semantics**: each backfill day is independent. If day 2 fails,
days 1 and 3 still complete. The CLI exits with code 0 if all days
succeed, or 1 if any day failed. Each day gets its own
`pipeline_execution_logs` row (with the `run_id` and `target_date`).

### Silver transformation

The dbt project under `dbt_project/` materializes the Silver tier of the
OFAE medallion. Each Silver model reads raw JSON from the Bronze S3 bucket
(or local mirror in dev) and produces clean Parquet tables.

Running:

```bash
# Local dev (uses local DuckDB file)
OMCAE_DBT_TARGET=dev OMCAE_USE_LOCAL_BRONZE=true \
  uv run dbt build --project-dir dbt_project

# Production (reads S3 directly via DuckDB httpfs)
OMCAE_DBT_TARGET=prod OMCAE_BRONZE_PATH=s3://ofae-data-lakehouse-bronze-prod/otter \
  uv run dbt build --project-dir dbt_project
```

Via the CLI (`omc-ingest silver run-silver`):

```bash
# Run all Silver models
omc-ingest silver run-silver

# Run only silver_reports
omc-ingest silver run-silver --select silver_reports
```

Models:

- `silver_orders` (incremental+merge, unique on `(order_id, source_marketplace)`).
  One row per Otter order line item. Includes PII columns as raw SHA-256
  (no salt yet — PR4 will add the salt and re-materialize via
  `dbt run --full-refresh`).
- `silver_reports` (PR3b): one row per Otter report job, joining
  `bronze.reports_enqueue` and `bronze.reports_result` by `job_id`.
  Exposes `gross_sales_amount`, `net_payout_amount`, and `result_status`
  (READY/FAILED/CANCELLED).

Data quality tests per PRD §5.3:

- `not_null` on `order_id`, `source_marketplace`, `total_amount`, and other revenue vars.
- Composite `unique` on `(order_id, source_marketplace)`.
- Custom data test: warn if any `total_amount` equals 0 (per PRD §5.3 anomaly policy).

## Architecture

```
CLI (Click)
  └─ run_bronze_impl (pure, testable)
       ├─ OAuthRefresher.ensure_fresh_token()
       │    └─ SecretsPort (InMemorySecrets PR1 → KMS PR2a)
       ├─ OtterClient.fetch_orders() → BronzeWriter.write_raw(orders)
       ├─ OtterClient.request_report() → BronzeWriter.write_raw(reports_enqueue)
       ├─ poll_report_until_ready() → BronzeWriter.write_raw(reports_result)
       └─ LogsPort (InMemoryLogs PR1 → PostgresLogs PR2a)
```
