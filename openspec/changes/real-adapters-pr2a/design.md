# Design: Real Adapters — KMSSecrets + PostgresLogs + Config Wiring (PR2a)

## Technical Approach

Hexagonal swap: add `KMSSecrets` and `PostgresLogs` as Protocol-conformant adapters. `build_run_context` becomes the factory switchboard, reading `OMCAE_SECRETS_BACKEND` to select impl. Zero call-site changes in `run_bronze_impl`. Keep `InMemorySecrets`/`InMemoryLogs` for `memory` backend (dev path).

## Module Layout (Additions)

```
src/omc_analytics/common/
├── kms_secrets.py           ← NEW: KMSSecrets adapter (~110 LOC)
├── postgres_logs.py         ← NEW: PostgresLogs adapter (~90 LOC)
└── migrations/
    └── 001_create_pipeline_execution_logs.sql  ← NEW (~14 LOC)

src/omc_analytics/common/config.py  ← MODIFIED: validate_config + backend factory (~40 LOC delta)

tests/
├── unit/common/test_config_validation.py      ← NEW (~40 LOC)
├── integration/test_kms_secrets.py            ← NEW (~80 LOC)
└── integration/test_postgres_logs.py          ← NEW (~70 LOC)
```

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Encryption pattern | Envelope (`generate_data_key` + AES-256-GCM) | Per-merchant blast-radius isolation; no 4KB KMS payload cap; PRD §2.3 exact match |
| Postgres driver | psycopg2 + `ThreadedConnectionPool` (min 1, max 5) | Already runtime dep; no async story; simplest for v1 logger |
| Unit-test log backing | SQLite fake (tests/ only) | testcontainers adds 20-30s/run; SQLite covers 95% of scenarios |
| Integration-test Postgres | `testcontainers[postgres]` fixture, one test | Catches driver/version mismatches; ephemeral container, no real DB |
| InMemory + real coexist | Both stay | `OMCAE_SECRETS_BACKEND=memory` is local-dev path; removing breaks 149 PR1 tests |
| KMS client injection | Constructor receives `boto3.client("kms")` | Matches hexagonal pattern from `BronzeWriter`; moto substitutes in tests |
| Nonce generation | `os.urandom(12)` per `save` | Fresh nonce per encryption; tested for uniqueness across 1000 calls |

## KMSSecrets Class

```
KMSSecrets(conn_factory: Callable[[], connection], kms_client, key_id: str)
  └─ _cipher: AESGCM   (from cryptography.hazmat)
```

### `save(creds: MerchantCredentials)`
1. Serialise `creds` → JSON bytes `payload`
2. `kms.generate_data_key(KeyId=key_id, KeySpec="AES_256")` → `(Plaintext, CiphertextBlob)`
3. `nonce = os.urandom(12)`
4. `encrypted = AESGCM(Plaintext).encrypt(nonce, payload, None)`
5. `INSERT INTO merchant_credentials (merchant_id, key_id, ciphertext_blob, encrypted_payload, nonce) ...`
6. `Plaintext[:] = b'\x00' * 32` (zeroize via bytearray)

### `load(merchant_id: str) -> MerchantCredentials`
1. `SELECT key_id, ciphertext_blob, encrypted_payload, nonce FROM merchant_credentials WHERE merchant_id = %s`
2. If no row → raise `MerchantNotFoundError`
3. `Plaintext = kms.decrypt(CiphertextBlob=ciphertext_blob)["Plaintext"]`
4. `payload = AESGCM(Plaintext).decrypt(nonce, encrypted_payload, None)`
5. `Plaintext[:] = b'\x00' * 32` (zeroize)
6. Deserialise `payload` → `MerchantCredentials`; return

Blob table schema: `merchant_credentials(merchant_id TEXT PK, key_id TEXT, ciphertext_blob BYTEA, encrypted_payload BYTEA, nonce BYTEA, created_at TIMESTAMPTZ DEFAULT now())`.

## PostgresLogs Class

```
PostgresLogs(pool: ThreadedConnectionPool)
```

### Connection context manager
```python
@contextmanager
def _conn(self):
    conn = self._pool.getconn()
    try: yield conn
    finally: self._pool.putconn(conn)
```

### `insert_started(row: RunLog) -> UUID`
```sql
INSERT INTO pipeline_execution_logs (id, merchant_id, run_id, pipeline_name, status, started_at)
VALUES (%s, %s, %s, %s, 'STARTED', %s)
RETURNING run_id
```

### `update_finished(run_id, status, error_class, error_message)`
```sql
UPDATE pipeline_execution_logs
SET status=%s, finished_at=NOW(), error_class=%s, error_message=%s
WHERE run_id=%s
```
Check `cursor.rowcount == 0` → raise `RunNotFoundError`.

## SQLite Fake (tests/ only)

`tests/conftest.py` provides `sqlite_logs` fixture: creates `:memory:` SQLite, applies DDL (with `TEXT` for `TIMESTAMPTZ`, `UUID`, `BYTEA`), returns `PostgresLogs`-compatible object. Used in all unit tests for logs.

## Config Wiring

`validate_config()` helper, called before `build_run_context` in CLI path:

| Backend | Required Vars | Default |
|---------|--------------|---------|
| `memory` | none | — |
| `kms` | `OMCAE_KMS_KEY_ID`, `OMCAE_PG_DSN` | `OMCAE_AWS_REGION=us-east-1` |

`build_run_context` now accepts `secrets_backend: Literal["memory","kms"] = "memory"` and instantiates the correct `SecretsPort`. `PostgresLogs` constructed when `OMCAE_PG_DSN` is set; falls back to `InMemoryLogs` otherwise.

## Test Harness

- **moto**: `@mock_aws` decorator (moto 5.x unified API) for S3 + KMS. `conftest.py` adds `aws_credentials` fixture and `kms_client` fixture.
- **testcontainers**: `postgres_container` session-scoped fixture starts `postgres:16-alpine`, returns `OMCAE_PG_DSN`, applies DDL, destroys at teardown.
- **SQLite fixture**: `sqlite_logs` for unit tests — in-memory, DDL-applied, same `LogsPort` surface.

## Out of Scope (PR2b+)

- `--backfill` flag, backfill loop, `backfill_dates` generator, `compute_window_for_date` helper
- dbt, Silver/Gold, PII, COGS, Streamlit UI, OAuth `authorization_code`, webhooks, cron, schema migration tooling, KMS key rotation

## Risks

| Risk | Mitigation |
|------|------------|
| Nonce reuse | `os.urandom(12)` per call; unit test 1000-call uniqueness assertion |
| Pool leak on exception | `try/finally` context manager; test exception path |
| moto 5.x API drift | Pin `moto>=5.0.0,<6.0.0`; `@mock_aws` decorator; CI smoke test |
| Data key survives in memory | `bytearray` zeroize; test asserts all-zero after save/load |
| Connection pool exhaustion under load | `maxconn=5` for CLI single-run; throttle not an issue for v1 |

## Locked Decisions (from PR2 Umbrella)

1. Envelope encryption with `generate_data_key` + AES-256-GCM
2. psycopg2 + `ThreadedConnectionPool` (not psycopg3)
3. SQLite fake for unit tests, testcontainers for 1 integration test
4. Order-date partition key (PR1 lock, unchanged)
5. Keep `InMemorySecrets` + `InMemoryLogs` alongside real impls
