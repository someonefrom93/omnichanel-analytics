# Tasks: Real Adapters — KMSSecrets + PostgresLogs + Config Wiring (PR2a)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~430 |
| Estimated file count | 11 (7 new, 4 modified) |
| Estimated test count | 14 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Already a chained slice (PR2a of umbrella) |
| Delivery strategy | exception-ok |
| Chain strategy | feature-branch-chain (PR2 umbrella tracker) |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: feature-branch-chain
400-line budget risk: Low

## Phase 1: Foundation (pyproject + DDL)

- [ ] 1.1 **pyproject.toml fixes** — Bump `moto` extras to `[s3,kms]`; add `psycopg2-binary` to runtime deps; add `testcontainers[postgres]` to dev deps. Files: `pyproject.toml`. *Done when: `uv sync` succeeds with new deps.*

- [ ] 1.2 **SQL DDL migration** — Create `src/omc_analytics/common/migrations/001_create_pipeline_execution_logs.sql` with the locked 9-column schema (id UUID PK, merchant_id, run_id, pipeline_name, status CHECK, started_at, finished_at, error_class, error_message). Files: `migrations/001_create_pipeline_execution_logs.sql`. Design refs: §PostgresLogs, §Locked schema. *Test-first: `test_ddl_applies_to_sqlite` — apply DDL to in-memory SQLite, assert table + columns exist.* *Done when: test green, DDL file ready.*

## Phase 2: KMSSecrets Adapter

- [ ] 2.1 **KMSSecrets tests (RED)** — `test_save_load_roundtrip` (envelope encrypt→decrypt), `test_nonce_uniqueness` (1000 calls), `test_plaintext_zeroized_after_save`, `test_load_unknown_merchant_raises`. Files: `tests/integration/test_kms_secrets.py`. Spec refs: spec.md §KMSSecrets Envelope Encryption Roundtrip (all 4 scenarios). Design refs: §KMSSecrets class. *Done when: 4 failing tests (RED).*

- [ ] 2.2 **KMSSecrets impl (GREEN)** — `common/kms_secrets.py`: `KMSSecrets` class with `save`/`load` (envelope encrypt/decrypt per design algorithm), `MerchantNotFoundError` on missing, `bytearray` zeroize. Constructor injects `conn_factory`, `kms_client`, `key_id`. Files: `src/omc_analytics/common/kms_secrets.py`. Design refs: §KMSSecrets class. *Done when: 4 tests green, coverage ≥80%.*

## Phase 3: PostgresLogs Adapter

- [ ] 3.1 **PostgresLogs tests (RED)** — `test_insert_started_returns_run_id`, `test_update_finished_sets_success`, `test_update_finished_unknown_raises`, `test_ddl_creates_table`. Files: `tests/integration/test_postgres_logs.py`. Spec refs: spec.md §PostgresLogs Insert and Update (all 4 scenarios). Design refs: §PostgresLogs class. *Done when: 4 failing tests (RED).*

- [ ] 3.2 **PostgresLogs impl (GREEN)** — `common/postgres_logs.py`: `PostgresLogs` with `ThreadedConnectionPool`, `_conn()` context manager (guarantees `putconn`), `insert_started`/`update_finished` SQL per design. Files: `src/omc_analytics/common/postgres_logs.py`. Design refs: §PostgresLogs class. *Done when: 4 tests green, coverage ≥80%.*

## Phase 4: SQLite Fake Logs (test harness)

- [ ] 4.1 **SQLite fake fixture** — Add `sqlite_logs` fixture to `tests/conftest.py`: in-memory SQLite, DDL applied, same `LogsPort` surface for unit tests. Files: `tests/conftest.py`. Design refs: §SQLite Fake. *Done when: unit tests can import and use `sqlite_logs`.*

## Phase 5: Config Wiring

- [ ] 5.1 **Config validation tests (RED)** — `test_memory_backend_uses_inmemory` (default), `test_kms_backend_selects_kmssecrets` (with env vars), `test_missing_kms_key_id_raises`, `test_missing_pg_dsn_raises`. Files: `tests/unit/common/test_config_validation.py`. Spec refs: spec.md §Config Wiring Per Backend (all 4 scenarios). Design refs: §Config Wiring. *Done when: 4 failing tests (RED).*

- [ ] 5.2 **Config impl (GREEN)** — Update `common/config.py`: `validate_config()` function (raises `ConfigError` naming missing var), `build_run_context` accepts `secrets_backend` param (default `"memory"`), instantiates `KMSSecrets` or `InMemorySecrets`; `PostgresLogs` when `OMCAE_PG_DSN` set else `InMemoryLogs`. Files: `src/omc_analytics/common/config.py`. Design refs: §Config Wiring. *Done when: 4 tests green.*

## Phase 6: Integration Test

- [ ] 6.1 **End-to-end integration test** — `test_run_bronze_impl_with_real_adapters`: moto[s3,kms] + testcontainers Postgres, pre-seeded `InMemorySecrets`, `OMCAE_SECRETS_BACKEND=kms`, assert 3+ S3 objects + SUCCESS log row. Files: `tests/integration/test_bronze_end_to_end_real.py`. Spec refs: spec.md §End-to-End Integration. Design refs: §Test Harness. *Done when: test green, no real AWS/DB calls.*

- [ ] 6.2 **testcontainers + moto fixtures** — Add `postgres_container` (session-scoped, postgres:16-alpine, returns DSN) and `kms_client` (moto KMS) fixtures to `conftest.py`. Files: `tests/conftest.py`. Design refs: §Test Harness. *Done when: fixtures are importable and usable by integration tests.*

## Phase 7: Polish

- [ ] 7.1 **README update** — Replace "What's Next (PR2+)" with "What Ships (PR2a)" listing KMSSecrets + PostgresLogs adapters; add "Local dev without AWS" subsection documenting `OMCAE_SECRETS_BACKEND=memory` path. Files: `README.md`.

- [ ] 7.2 **.env.example** — Create `.env.example` enumerating `OMCAE_SECRETS_BACKEND`, `OMCAE_PG_DSN`, `OMCAE_KMS_KEY_ID`, `OMCAE_AWS_REGION` with example values and comments. Files: `.env.example`.

- [ ] 7.3 **Lint & coverage gate** — `ruff check src/ tests/`, `mypy src/omc_analytics/`, `pytest --cov=src/omc_analytics/common/ --cov-fail-under=80`. *Done when: ruff + mypy + black clean, coverage ≥80% on common/.*
