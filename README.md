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

## Architecture (PR1)

```
CLI (Click)
  └─ run_bronze_impl (pure, testable)
       ├─ OAuthRefresher.ensure_fresh_token()
       │    └─ SecretsPort (InMemorySecrets PR1 → KMS PR2)
       ├─ OtterClient.fetch_orders() → BronzeWriter.write_raw(orders)
       ├─ OtterClient.request_report() → BronzeWriter.write_raw(reports_enqueue)
       ├─ poll_report_until_ready() → BronzeWriter.write_raw(reports_result)
       └─ LogsPort (InMemoryLogs PR1 → Postgres PR2)
```

## What's Next (PR2+)

- KMS-backed `SecretsPort` (replaces `InMemorySecrets`)
- Postgres-backed `LogsPort` (replaces `InMemoryLogs`)
- Silver transformation layer (`transformation/`)
- Docker containerization and scheduled orchestration
- End-to-end encrypted credential bootstrap flow