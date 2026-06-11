# Delta Spec: Real Adapters (PR2a)

> Covers KMSSecrets, PostgresLogs, config wiring, test harness. Backfill loop deferred to PR2b.

## ADDED Requirements

### Requirement: KMSSecrets Envelope Encryption Roundtrip

The system MUST encrypt a `MerchantCredentials` payload via envelope encryption (`kms.generate_data_key` + AES-256-GCM) on `save` and decrypt it on `load`, producing the original payload byte-for-byte.

#### Scenario: Save roundtrips through encrypt-then-decrypt

- GIVEN a `KMSSecrets` instance wired to a moto-mocked KMS client
- WHEN `save(creds)` is called with `MerchantCredentials(merchant_id="M1", ...)`
- THEN `load("M1")` returns a `MerchantCredentials` with the same field values
- AND the stored blob contains `key_id`, `ciphertext_blob`, `encrypted_payload`, `nonce`

#### Scenario: Each save generates a fresh nonce

- GIVEN 3 consecutive `save` calls for the same merchant
- WHEN nonces are compared across the 3 stored blobs
- THEN all 3 nonces are distinct (12 random bytes each)

#### Scenario: Plaintext data key is zeroized after use

- GIVEN a `save` operation completes
- WHEN the plaintext data key bytearray is inspected
- THEN it contains only zero bytes (zeroized before dropping reference)

#### Scenario: Load raises MerchantNotFoundError for unknown merchant

- GIVEN no credentials exist for `merchant_id="X99"`
- WHEN `load("X99")` is called
- THEN `MerchantNotFoundError` is raised

### Requirement: PostgresLogs Insert and Update

The system MUST insert a STARTED row with the 9-column `pipeline_execution_logs` schema and return a `run_id`, then update the row to SUCCESS/FAILED with optional error fields.

#### Scenario: insert_started writes row and returns run_id

- GIVEN a `PostgresLogs` connected to a fresh test database with DDL applied
- WHEN `insert_started(RunLog(...))` is called
- THEN a row exists in `pipeline_execution_logs` with `status="STARTED"` and 9 non-null structural columns
- AND the returned `run_id` matches the row

#### Scenario: update_finished transitions to SUCCESS

- GIVEN a STARTED row exists for `run_id=R1`
- WHEN `update_finished(run_id=R1, status="SUCCESS", error_class=None, error_message=None)` is called
- THEN the row's `status` is `"SUCCESS"` and `finished_at` is not null

#### Scenario: update_finished raises RunNotFoundError on unknown run_id

- GIVEN no row exists for `run_id=R99`
- WHEN `update_finished(run_id=R99, ...)` is called
- THEN `RunNotFoundError` is raised

#### Scenario: DDL applies cleanly against fresh database

- GIVEN a freshly created PostgreSQL database (or in-memory SQLite for unit tests)
- WHEN the `001_create_pipeline_execution_logs.sql` DDL is executed
- THEN the `pipeline_execution_logs` table exists with all 9 columns, a `CHECK` constraint on `status`, and indexes on `merchant_id` and `run_id`

### Requirement: Config Wiring Per Backend

The system MUST select the `SecretsPort` and `LogsPort` implementation based on `OMCAE_SECRETS_BACKEND` and validate required environment variables, raising clear errors when requirements are not met.

#### Scenario: OMCAE_SECRETS_BACKEND=memory selects InMemorySecrets (default)

- GIVEN `OMCAE_SECRETS_BACKEND` is unset or `"memory"`
- WHEN `build_run_context` is called
- THEN `InMemorySecrets` is used (PR1 behaviour preserved)

#### Scenario: OMCAE_SECRETS_BACKEND=kms selects KMSSecrets

- GIVEN `OMCAE_SECRETS_BACKEND=kms`, `OMCAE_KMS_KEY_ID=alias/my-key`, `OMCAE_PG_DSN=postgresql://localhost/test`
- WHEN `build_run_context` constructs dependencies
- THEN `KMSSecrets` is wired as the `SecretsPort` implementation

#### Scenario: Missing KMS_KEY_ID raises ConfigError

- GIVEN `OMCAE_SECRETS_BACKEND=kms` but `OMCAE_KMS_KEY_ID` is unset
- WHEN `validate_config()` runs
- THEN a `ConfigError` is raised mentioning the missing var name `OMCAE_KMS_KEY_ID`

#### Scenario: Missing PG_DSN raises ConfigError

- GIVEN `OMCAE_PG_DSN` is unset and a Postgres adapter is requested
- WHEN `validate_config()` runs
- THEN a `ConfigError` is raised mentioning the missing var `OMCAE_PG_DSN`

### Requirement: End-to-End Integration with Real Adapters

The system MUST execute `run_bronze_impl` successfully with KMSSecrets + PostgresLogs against moto[s3,kms] + testcontainers Postgres, writing Bronze S3 objects and pipeline execution log rows.

#### Scenario: run_bronze_impl succeeds with KMSSecrets + PostgresLogs

- GIVEN moto S3 + moto KMS are active and a testcontainers Postgres has the DDL applied
- AND `OMCAE_SECRETS_BACKEND=kms`, all env vars are set, `InMemorySecrets` is pre-seeded with credentials
- WHEN `run_bronze_impl(run_ctx)` completes
- THEN at least 3 S3 objects exist in the Bronze bucket under `merchant_id=M1/`
- AND `pipeline_execution_logs` contains a row with `status="SUCCESS"` and `merchant_id="M1"`

## MODIFIED Requirements

### Requirement: No Live Network Calls During pytest (local-test-mocking §No Live Network Calls)

The test suite MUST NOT make real HTTP or AWS calls. All S3 and KMS operations SHALL be intercepted by moto.
(Previously: only `moto[s3]` was required; PR2a adds `moto[kms]` interception.)

#### Scenario: All S3 operations handled by moto (unchanged)

- GIVEN `moto[s3]` mocks the S3 service
- WHEN `bronze_writer.put_object()` is called
- THEN the call is handled in-memory by moto
- AND no real AWS S3 API call is made

#### Scenario: All KMS operations handled by moto

- GIVEN `moto[kms]` mocks the KMS service
- WHEN `KMSSecrets.save()` calls `kms.generate_data_key`
- THEN the call is handled in-memory by moto
- AND no real AWS KMS API call is made

#### Scenario: Testcontainers Postgres provides isolated database

- GIVEN a `testcontainers[postgres]` container is started as a pytest fixture
- WHEN DDL is applied and adapter operations execute
- THEN all operations target the ephemeral container
- AND no real RDS or external PostgreSQL is contacted
- AND the container is destroyed after the test session
