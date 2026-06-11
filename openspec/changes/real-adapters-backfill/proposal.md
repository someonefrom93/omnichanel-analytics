# Proposal: Real Adapters & 30-Day Backfill (PR2)

## Intent

Replace the two PR1 stub ports (`InMemorySecrets`, `InMemoryLogs`) with real production adapters — `KMSSecrets` (envelope encryption, AES-256-GCM) and `PostgresLogs` (real `pipeline_execution_logs` DDL) — and add the 30-day backfill loop required by PRD §2.1 ("Historical Backfill Automation"). Hexagonal layering from PR1 means call sites in `run_bronze_impl` and the Otter/Bronze adapters stay unchanged; PR2 only swaps wiring in `build_run_context` and adds the loop wrapper.

The hexagonal `SecretsPort` / `LogsPort` Protocols and the 9-column `pipeline_execution_logs` schema were locked in PR1 design.md. This change materializes them.

## Scope

### In Scope

1. **`KMSSecrets` adapter** — envelope encryption via boto3 KMS + AES-256-GCM payload encryption, Postgres-backed encrypted blob storage. New `OMCAE_SECRETS_BACKEND=memory|kms` env flag (default `memory` for local dev).
2. **`PostgresLogs` adapter** — real PostgreSQL DDL for `pipeline_execution_logs` matching the locked 9-column schema. `psycopg2-binary` connection pool. SQL migration file under `src/omc_analytics/common/migrations/001_create_pipeline_execution_logs.sql`.
3. **30-day backfill loop** — new `--backfill` and `--backfill-days N` flags on the `run-bronze` Click command; one `run_id` and one `pipeline_execution_logs` row per iteration; idempotent re-runs of the same date.
4. **Config wiring** — `build_run_context` reads `OMCAE_SECRETS_BACKEND`, `OMCAE_PG_DSN`, `OMCAE_KMS_KEY_ID`, `OMCAE_AWS_REGION`; validates required vars per backend.
5. **Integration tests** — one end-to-end integration test (`run_bronze_impl` against `moto[s3,kms]` + a real local Postgres) and one backfill loop test (3 iterations).
6. **Documentation** — README "What's next" updated; `.env.example` enumerating all env vars; "Local dev without AWS" subsection.
7. **Dependency changes** — `pyproject.toml` dev-deps: `moto[s3]` → `moto[s3,kms]`. Runtime: no new top-level deps (`psycopg2-binary`, `cryptography`, `boto3` already present).

### Out of Scope (PR3+)

- dbt-core / dbt-duckdb installation, models, or transformations (PR3)
- Silver Parquet tier (PR3)
- PII SHA-256 masking (PR4)
- Gold star schema / `fact_financial_sales` (PR4+)
- Streamlit UI (PR5)
- `merchant_cogs` schema and COGS admin (PR5)
- `authorization_code` OAuth flow (PR5)
- Webhooks (PR6+)
- Cron / EventBridge scheduling (deployment concern)
- KMS key rotation logic (deferred to a future PR after envelope pattern is proven)
- Multi-region KMS replication
- Schema migration tooling (Alembic / yoyo-migrations) — single-file DDL only this PR

## Capabilities

### New Capabilities

- `secrets-kms-adapter`: `KMSSecrets` real adapter (envelope encryption, AES-256-GCM) — new full spec.
- `logs-postgres-adapter`: `PostgresLogs` real adapter + `pipeline_execution_logs` DDL — new full spec.
- `backfill-loop`: `--backfill` flag, 30-day window iteration, idempotency contract — new full spec.

### Modified Capabilities

- `bronze-ingestion`: one delta — `build_bronze_key` filename timestamp vs backfill-day partition tradeoff must be locked (see ADR §6). Call sites in `run_bronze_impl` do NOT change.
- `local-test-mocking`: one delta — `moto[s3,kms]` replaces `moto[s3]`. New `testcontainers[postgres]` (or SQLite-backed fake) fixture added for integration tests.

## Approach

### 1. Hexagonal swap (no call-site changes)

`build_run_context` switches on `OMCAE_SECRETS_BACKEND`. `memory` → `InMemorySecrets` (PR1, kept for unit tests + dev); `kms` → `KMSSecrets(dsn=OMCAE_PG_DSN, kms_client=boto3.client("kms", region_name=OMCAE_AWS_REGION), key_id=OMCAE_KMS_KEY_ID)`. Same Protocol, no caller changes.

`build_run_context` also instantiates `PostgresLogs(dsn=OMCAE_PG_DSN)` by default; an `OMCAE_LOGS_BACKEND=memory` flag is OPTIONAL (lower friction to just require Postgres for PR2 and document it; decide in sdd-design if a dev-no-pg shortcut is worth the lines).

### 2. Envelope encryption design (locked via pre-approved decision)

**Pattern** (matches PRD §2.3 exactly):
- **Write**: `KMSSecrets.save(creds)` →
  1. `kms.generate_data_key(KeyId=OMCAE_KMS_KEY_ID, KeySpec="AES_256")` → returns `(Plaintext, CiphertextBlob)`.
  2. AES-256-GCM encrypt the credential payload using `Plaintext` (32 bytes) + a fresh 12-byte nonce + 16-byte salt via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.
  3. Persist `merchant_credentials` row: `(merchant_id, key_id, ciphertext_blob, encrypted_payload, nonce, salt)`. Drop `Plaintext` from memory.
- **Read**: `KMSSecrets.load(merchant_id)` →
  1. `kms.decrypt(CiphertextBlob=ciphertext_blob)` → recovers `Plaintext` data key.
  2. AES-256-GCM decrypt the payload with the recovered key + stored nonce.
  3. Return reconstructed `MerchantCredentials`. Drop `Plaintext` immediately after decrypt.
- **Tests**: `moto[s3,kms]` decorates the integration test; `generate_data_key` / `decrypt` are stubbed and return deterministic test keys.

The `KMSSecrets` class follows the exact hexagonal pattern as `BronzeWriter`: receives the `boto3.client("kms")` injected, never constructs it. ADR §6 documents this.

### 3. Postgres DDL & pool

`psycopg2-binary` (already a runtime dep — `pyproject.toml:18`) via `psycopg2.pool.ThreadedConnectionPool` (minconn=1, maxconn=5). Simpler than psycopg3 + `psycopg_pool` (no new dep, no async story, lower mental load for a v1 logging adapter that writes a few rows per run). `ThreadedConnectionPool` returns a context-manager wrapper to guarantee `putconn` on exceptions.

DDL file `src/omc_analytics/common/migrations/001_create_pipeline_execution_logs.sql`:
- `id UUID PRIMARY KEY`
- `merchant_id VARCHAR(64) NOT NULL` (indexed)
- `run_id UUID NOT NULL` (indexed)
- `pipeline_name VARCHAR(64) NOT NULL`
- `status VARCHAR(16) NOT NULL CHECK (status IN ('STARTED','SUCCESS','FAILED'))`
- `started_at TIMESTAMPTZ NOT NULL`
- `finished_at TIMESTAMPTZ`
- `error_class VARCHAR(128)`
- `error_message TEXT`

The integration test applies this DDL against a fresh schema on connection; the README documents manual application for production.

### 4. Backfill loop

CLI surface:
- `omc-ingest run-bronze --merchant-id M1 --env dev` → current T-1 behavior (unchanged).
- `omc-ingest run-bronze --merchant-id M1 --env dev --backfill` → iterate last 30 days.
- `omc-ingest run-bronze --merchant-id M1 --env dev --backfill --backfill-days 7` → iterate last 7 days (cap 90).

Loop in `run.py`:
```python
for target_date in backfill_dates(now_utc, store_tz, days=N):  # yields date in store-local
    window = compute_window_for_date(store_tz, target_date)  # NEW pure helper
    iteration_run_id = uuid4()
    iteration_run_ts = datetime.now(UTC)
    run_bronze_for_window(ctx, window, iteration_run_id, iteration_run_ts)
    # one LogsPort row per iteration
```

Each iteration: fresh `run_id` + `run_timestamp_utc` → distinct S3 filenames per run → BUT the Hive partition `day=DD` reflects the **order date** (target_date), not the run date. **Idempotency decision**: a re-run of the same backfill date overwrites the same `day=DD` partition objects, but with a new run timestamp in the filename — that is, the path is *partition-stable* (`day=DD` matches the order date) but *filename-distinct* (timestamp reflects the run). This is the choice that matches the S3 multi-tenant fencing model and the existing `build_bronze_key` contract from PR1.

**Tradeoff accepted**: Re-running the same backfill date creates N timestamped objects under the same partition. Cleanest alternative — overwrite the same key with deterministic filename — is rejected because the PR1 spec (`bronze-ingestion/spec.md` §Bronze S3 Path Correctness, SCN-014) LOCKS `run_timestamp_utc` in the filename. Changing that would require a delta spec on PR1's locked contract. We accept N-version objects and let Silver (PR3) pick the latest at transform time.

If a stronger "overwrite the same key per order-date" guarantee is needed later, it's a separate PR with a delta on the bronze-ingestion spec.

### 5. Configuration wiring

`build_run_context` (or a new `_build_real_deps` factory) reads:
- `OMCAE_SECRETS_BACKEND` (default `memory`; values: `memory`, `kms`)
- `OMCAE_PG_DSN` (required when `secrets=kms` OR `logs=postgres`; format `postgresql://user:pass@host:port/dbname`)
- `OMCAE_KMS_KEY_ID` (required when `secrets=kms`; AWS KMS CMK ARN or alias)
- `OMCAE_AWS_REGION` (default `us-east-1`)

Validation: a `validate_config()` helper called at CLI startup fails loudly with a clear error message if a required var is missing for the chosen backend. Test: `test_missing_kms_key_id_raises_value_error` etc.

### 6. ADR — Envelope encryption pattern

> **ADR-002: Use envelope encryption with `generate_data_key` + AES-256-GCM, not direct KMS Encrypt.**
>
> **Context**: PRD §2.3 mandates AES-256-GCM via the `cryptography` library and a flat ~$1/mo infra overhead. Two patterns satisfy this: (A) envelope encryption with per-record data keys from KMS, or (B) a single CMK used directly via `kms.encrypt`/`kms.decrypt` (no data key).
>
> **Decision**: Pattern A (envelope). The CMK is used to wrap a per-merchant 256-bit data key; the data key encrypts the credential payload locally; the wrapped data key (CiphertextBlob) is stored alongside the encrypted payload in `merchant_credentials`.
>
> **Rationale**:
> - Per-merchant data key limits blast radius: a leaked data key compromises one merchant, not the whole table.
> - Avoids the 4 KB KMS API payload limit on direct `kms.encrypt` (`merchant_credentials` payloads can carry nested JSON; envelope sidesteps this).
> - Matches the AWS-recommended pattern for at-rest envelope encryption in relational stores.
> - Same cost profile as direct KMS (one CMK, $1/mo) — data-key generation is free up to the free tier and pennies beyond.
>
> **Consequence**: `KMSSecrets` MUST zero out the `Plaintext` data key after encrypt/decrypt. Tests assert no `Plaintext` survives in any persisted row. Future key-rotation strategy: re-encrypt the data key under a new CMK; defer the full rotation tool to a follow-up PR.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `pyproject.toml` | Modified | `moto[s3]` → `moto[s3,kms]` in dev-deps; add `testcontainers[postgres]` (or `sqlite` if chosen — see fork §B) |
| `src/omc_analytics/common/kms_secrets.py` | New | `KMSSecrets` envelope-encryption adapter (~110 LOC) |
| `src/omc_analytics/common/postgres_logs.py` | New | `PostgresLogs` adapter with pool (~90 LOC) |
| `src/omc_analytics/common/migrations/001_create_pipeline_execution_logs.sql` | New | Locked 9-column DDL (~12 lines) |
| `src/omc_analytics/common/config.py` | Modified | `build_run_context` switches SecretsPort impl by env; adds `validate_config` (~40 LOC delta) |
| `src/omc_analytics/ingestion/run.py` | Modified | Add `--backfill` / `--backfill-days` flags + loop wrapper; add `compute_window_for_date` helper (~60 LOC delta) |
| `tests/integration/test_kms_secrets.py` | New | Envelope encrypt/decrypt round-trip + moto KMS (~80 LOC) |
| `tests/integration/test_postgres_logs.py` | New | DDL apply + insert/update against Postgres (~70 LOC) |
| `tests/integration/test_bronze_end_to_end_real.py` | New | `run_bronze_impl` against `moto[s3,kms]` + Postgres (~90 LOC) |
| `tests/integration/test_backfill_loop.py` | New | 3-iteration backfill against the same harness (~70 LOC) |
| `tests/unit/common/test_config_validation.py` | New | Missing env var raises ValueError (~40 LOC) |
| `tests/unit/ingestion/test_backfill_window_helper.py` | New | `compute_window_for_date` purity (~30 LOC) |
| `README.md` | Modified | "What's next (PR2+)" → mark PR2 shipped; new "Local dev without AWS" subsection |
| `.env.example` | New | All env vars documented with examples |
| `tests/conftest.py` | Modified | Add `aws_credentials` fixture for moto KMS; `postgres_container` fixture (or SQLite fake) |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| LOC forecast (~520) exceeds 400-line PR review budget | **High** | Surface the split option (PR2a adapters / PR2b backfill) in the proposal; let user preflight decide. See `## Review Budget` below. |
| `moto[kms]` API drift (moto 5.x changed `mock_kms` imports) | Med | Pin `moto>=5.0.0,<6.0.0`; use `@mock_aws` decorator (moto 5 unified API); assert `generate_data_key` / `decrypt` work in CI before declaring done. |
| `psycopg2.pool.ThreadedConnectionPool` connection leak on exception | Med | `contextlib.contextmanager` wrapper that guarantees `putconn` in `finally`; test the exception path. |
| AES-256-GCM nonce reuse risk if implementation is sloppy | Low | Each `save` generates a fresh `os.urandom(12)` nonce; unit test asserts nonce uniqueness across 1000 calls. |
| Backfill loop runs 30× per invocation — exceeds Otter rate limits | Med | Honor PRD's 429 backoff inside the loop; each iteration is a fresh `OtterClient` call with PR1's 3-retry policy. If a merchant has 30 days × N endpoints, we serialize them; the loop does NOT parallelize. |
| Backfill partition key (order date) diverges from filename timestamp (run date) — confusing for ops | Med | Document explicitly in README "Backfill semantics" subsection; the run-timestamp-in-filename is locked by PR1 SCN-014. |
| Plaintext data key in memory after `decrypt` | Low | Zeroize via `bytearray` overwrite before dropping the reference; test asserts no `Plaintext` bytes survive. |
| `moto` test containers for Postgres slow CI by 30s+ per run | Med | Use SQLite-backed fake LogsPort for unit tests; reserve real Postgres for one integration test per PR. |

## Rollback Plan

1. Revert PR branch.
2. `aws s3 rm s3://ofae-data-lakehouse-bronze-{env}/otter/merchant_id=<id>/ --recursive` for any backfill windows written during PR2 testing.
3. `DROP TABLE pipeline_execution_logs` and `DROP TABLE merchant_credentials` if PR2 created them in a dev DB (NOT in prod — production schema is owned by an upstream DBA process; this PR only creates the DDL file).
4. `uv remove moto` extras; `uv add moto[s3]` to restore PR1 dev-deps state.
5. No PR1 contract changes — `InMemorySecrets` and `InMemoryLogs` are kept in the codebase as the default backend, so a reverted PR restores the stub behaviour automatically.

## Dependencies

**Runtime** (no new): `boto3`, `cryptography`, `psycopg2-binary`, `click`, `pydantic`, `requests`.

**Dev**: bump `moto[s3]` → `moto[s3,kms]`; add `testcontainers[postgres]` (or skip if SQLite fake chosen — see fork §B).

**AWS**: KMS CMK in `OMCAE_AWS_REGION` with `kms:GenerateDataKey` and `kms:Decrypt` IAM permissions for the runtime role.

**Postgres**: a reachable PostgreSQL instance (dev: local docker `postgres:16-alpine`; CI: `testcontainers[postgres]`; prod: managed RDS — out of PR2 scope to provision).

## Success Criteria

- [ ] `uv sync` + `pytest` green with ≥ 80% coverage on the new modules.
- [ ] `OMCAE_SECRETS_BACKEND=kms` integration test round-trips a credential through moto KMS + Postgres with no real AWS calls.
- [ ] `OMCAE_SECRETS_BACKEND=memory` keeps PR1 behaviour (regression test).
- [ ] `PostgresLogs` integration test applies the DDL, inserts a STARTED row, updates to SUCCESS, reads it back with all 9 columns correct.
- [ ] `--backfill` integration test runs 3 iterations against moto + Postgres, asserts 3 distinct S3 `day=` partitions and 3 `pipeline_execution_logs` rows.
- [ ] `--backfill --backfill-days 91` raises a clear ValueError (cap 90 enforced).
- [ ] Backfill re-run of the same date is idempotent at the partition level (same `day=DD` key) but creates new timestamped objects (per PR1's locked filename contract).
- [ ] README "What's next (PR2+)" updated; `.env.example` present and documents all 4 new env vars.
- [ ] No real AWS / Postgres / Otter network call during `pytest -m "not integration"`.
- [ ] ruff + mypy + black clean.
- [ ] Forecast and PR-split decision recorded before apply (see Review Budget below).

## Design Forks Surfaced (resolved below in Approach §6; documented here for sdd-spec context)

| Fork | Options | Chosen | Rationale |
|------|---------|--------|-----------|
| Encryption pattern | Direct KMS encrypt / Envelope (generate_data_key) | **Envelope** | Per-merchant blast-radius isolation; no 4 KB payload cap; AWS-recommended. Locked by orchestrator's pre-approved decision. |
| Postgres driver | psycopg2 + `ThreadedConnectionPool` / psycopg3 + `psycopg_pool` | **psycopg2** | Already a runtime dep; no async story yet; lowest friction for a v1 logging adapter. |
| Postgres in tests | `testcontainers[postgres]` / SQLite-backed fake LogsPort | **SQLite fake for unit; testcontainers for one integration** | testcontainers adds 20–30 s per CI run; SQLite fake covers 95% of unit scenarios; one real-Postgres integration test catches driver/version mismatches. |
| Backfill partition key | Order date / Run date | **Order date** (locked) | Matches PRD §2.2 Hive fencing model (`day=DD` is the partition, not the run). Filename timestamp stays as run (PR1 SCN-014 lock). |
| `InMemoryLogs` removal? | Drop / Keep alongside `KMSSecrets` / `PostgresLogs` | **Keep `InMemorySecrets` + `InMemoryLogs`** | Unit tests need them; `OMCAE_SECRETS_BACKEND=memory` is the local-dev no-AWS path. Removing them breaks 149 PR1 tests. |

## Estimated Changed Lines

| File | Approx. LOC delta |
|------|-------------------|
| `pyproject.toml` | 4 (bump moto extras; +1 dep) |
| `src/omc_analytics/common/kms_secrets.py` | 110 (new) |
| `src/omc_analytics/common/postgres_logs.py` | 90 (new) |
| `src/omc_analytics/common/migrations/001_create_pipeline_execution_logs.sql` | 14 (new) |
| `src/omc_analytics/common/config.py` | 40 (modified: env wiring + validation) |
| `src/omc_analytics/ingestion/run.py` | 60 (modified: backfill loop + helper) |
| `tests/integration/test_kms_secrets.py` | 80 (new) |
| `tests/integration/test_postgres_logs.py` | 70 (new) |
| `tests/integration/test_bronze_end_to_end_real.py` | 90 (new) |
| `tests/integration/test_backfill_loop.py` | 70 (new) |
| `tests/unit/common/test_config_validation.py` | 40 (new) |
| `tests/unit/ingestion/test_backfill_window_helper.py` | 30 (new) |
| `README.md` | 30 (modified: PR2 status + Local dev subsection) |
| `.env.example` | 20 (new) |
| `tests/conftest.py` | 15 (modified: moto+kms fixture, postgres fixture) |
| **Total forecast** | **≈ 763 LOC delta** |

## Review Budget

| Field | Value |
|-------|-------|
| Estimated changed lines | **~520 net code (excluding tests) / ~763 gross with tests** |
| 400-line budget risk | **High** |
| Chained PRs recommended | **Yes — split into PR2a (adapters) + PR2b (backfill loop) is the safest path** |
| Suggested split | See below |
| Delivery strategy | `ask-on-risk` |

**Decision needed before apply: Yes**

**Chained PRs recommended: Yes (advisory; orchestrator's preflight must ask the user)**

**400-line budget risk: High**

**Recommended split (advisory — user preflight required)**:

- **PR2a — Real adapters** (KMS + Postgres + config wiring + integration tests for the adapters): ~430 LOC. Just over budget on its own; the orchestrator's preflight can pre-approve the exception OR slice further.
- **PR2b — Backfill loop** (`--backfill` flag, 3-day integration test, `compute_window_for_date`): ~160 LOC. Comfortably under budget.

**Alternative — keep as single PR with `size:exception`**: ~520 LOC net code. User has been explicit about the 400-line rule in the persona, so this option should NOT be the default; the orchestrator's preflight must surface the choice.

The proposal records the forecast honestly and recommends PR2a/PR2b split; the user preflight decides.

---

*Proposal created by sdd-propose sub-agent · omnichannel-analytics project · change: real-adapters-backfill · 2026-06-11*
