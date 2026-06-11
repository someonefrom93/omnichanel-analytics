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

## What's Next

- [x] **PR2a** — KMSSecrets + PostgresLogs + Config wiring (DONE)
- [ ] **PR2b** — Backfill loop (`--backfill` flag, `compute_window_for_date`, `backfill_dates`)
- [ ] **PR3** — dbt Silver/Gold transformation layer
- [ ] Docker containerization and scheduled orchestration
- [ ] End-to-end encrypted credential bootstrap flow
- [ ] PII / COGS tracking
- [ ] Streamlit UI
- [ ] OAuth `authorization_code` flow, webhooks, cron
