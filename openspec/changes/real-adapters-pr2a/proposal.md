# Proposal: Real Adapters — KMSSecrets + PostgresLogs + Config Wiring (PR2a)

> **Umbrella**: `real-adapters-backfill` (PR2). **Split**: PR2a = adapters, PR2b = backfill loop (deferred).
> **Status**: Draft · **Date**: 2026-06-11 · **Forecast**: ~430 LOC delta

## Intent

Swap PR1's `InMemorySecrets`/`InMemoryLogs` stubs for real production adapters (`KMSSecrets` with envelope encryption, `PostgresLogs` with the locked 9-column DDL) and wire them into `build_run_context` via `OMCAE_SECRETS_BACKEND` env switch. Hexagonal call sites in `run_bronze_impl` stay unchanged.

## Scope

### In Scope

1. **KMSSecrets** — envelope encryption: `kms.generate_data_key` + AES-256-GCM via `cryptography`; Postgres blob store. Per PRD §2.3 and ADR-002.
2. **PostgresLogs** — real `pipeline_execution_logs` DDL + `psycopg2` `ThreadedConnectionPool`; `insert_started`/`update_finished` per the locked 9-column schema.
3. **SQL DDL** — `migrations/001_create_pipeline_execution_logs.sql`.
4. **Config wiring** — `OMCAE_SECRETS_BACKEND` (`memory`|`kms`), `OMCAE_PG_DSN`, `OMCAE_KMS_KEY_ID`; `validate_config()` fails loudly on missing required vars.
5. **Tests + pyproject** — moto extras `[s3,kms]`, `psycopg2-binary` runtime, `testcontainers[postgres]` dev; unit + integration tests; README `.env.example`.

### Out of Scope (PR2b+)

- Backfill loop (`--backfill` flag, `compute_window_for_date`, `backfill_dates` generator) → **PR2b**
- dbt, Silver, Gold, PII, COGS, Streamlit UI, OAuth `authorization_code`, webhooks, cron, schema migration tooling

## Capabilities

### New Capabilities

- `secrets-kms-adapter`: KMSSecrets envelope encryption, AES-256-GCM, Postgres blob store
- `logs-postgres-adapter`: PostgresLogs + pipeline_execution_logs DDL + connection pool

### Modified Capabilities

- `bronze-ingestion`: delta — `build_run_context` switches SecretsPort/LogsPort impl by env var
- `local-test-mocking`: delta — `moto[s3,kms]` replaces `moto[s3]`; testcontainers Postgres fixture

## Approach

Hexagonal swap: `build_run_context` reads `OMCAE_SECRETS_BACKEND` and instantiates `KMSSecrets` or `InMemorySecrets`. Same Protocols, zero call-site changes. Keep `InMemorySecrets`/`InMemoryLogs` for local dev.

## Design Forks Resolved

| Fork | Chosen |
|------|--------|
| Encryption pattern | Envelope (`generate_data_key` + AES-256-GCM) |
| Postgres driver | psycopg2 + ThreadedConnectionPool |
| Postgres in tests | SQLite fake (unit) + testcontainers (1 integration) |
| Partition key | Order date (unchanged from PR1) |
| InMemoryLogs removal? | Keep both alongside real impls |

## Affected Areas

| Area | Impact |
|------|--------|
| `common/kms_secrets.py` | New (~110 LOC) |
| `common/postgres_logs.py` | New (~90 LOC) |
| `common/migrations/001_create_pipeline_execution_logs.sql` | New (~14 LOC) |
| `common/config.py` | Modified (~40 LOC delta) |
| `pyproject.toml` | Modified (~6 LOC) |
| `tests/integration/test_kms_secrets.py` | New (~80 LOC) |
| `tests/integration/test_postgres_logs.py` | New (~70 LOC) |
| `tests/unit/common/test_config_validation.py` | New (~40 LOC) |
| `tests/conftest.py` | Modified (~15 LOC) |
| `README.md`, `.env.example` | New/Modified (~30 LOC) |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| AES-256-GCM nonce reuse | Low | Fresh `os.urandom(12)` per `save`; unit test asserts uniqueness across 1000 calls |
| Connection pool leak on exception | Med | Context manager guarantees `putconn` in `finally`; test the exception path |
| `moto[kms]` API drift (moto 5.x) | Med | Pin `moto>=5.0.0,<6.0.0`; use `@mock_aws` decorator |
| Plaintext data key in memory after decrypt | Low | Zeroize via `bytearray` overwrite; test asserts no `Plaintext` survives |

## Rollback Plan

1. Revert PR branch.
2. `DROP TABLE pipeline_execution_logs` and `DROP TABLE merchant_credentials` in dev DB.
3. Restore `moto[s3]` → remove `[kms]` extras.
4. `InMemorySecrets`/`InMemoryLogs` remain in codebase as `memory` backend default.

## Dependencies

**Runtime**: `boto3`, `cryptography`, `psycopg2-binary` (all present). **Dev**: `moto[s3,kms]`, `testcontainers[postgres]`. **AWS**: KMS CMK with `kms:GenerateDataKey` + `kms:Decrypt` IAM.

## Success Criteria

- [ ] `uv sync` + `pytest` green; ≥80% coverage on new modules
- [ ] `OMCAE_SECRETS_BACKEND=kms` integration test roundtrips credential through moto KMS + Postgres
- [ ] `OMCAE_SECRETS_BACKEND=memory` keeps PR1 behaviour (regression)
- [ ] `PostgresLogs` DDL applies cleanly; insert/update roundtrip with all 9 columns
- [ ] `validate_config` raises clear error for missing `OMCAE_KMS_KEY_ID` or `OMCAE_PG_DSN`
- [ ] `make check` clean (ruff + mypy + pytest)
- [ ] Forecast ≤ 450 LOC held
