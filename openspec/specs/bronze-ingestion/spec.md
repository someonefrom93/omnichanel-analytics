# Bronze Ingestion Specification

> Source: PRD §2.1, §2.2, §2.3 · Proposal: Scaffold Bronze Ingestion (PR1)
> Scope: PR1 only — dbt, Silver/Gold, UI, KMS round-trip, cron, backfill are out of scope.

## Purpose

Define the observable behaviour of the Otter HTTP client, OAuth token manager, rate-limit backoff, Bronze S3 writer, and CLI entrypoint that together constitute the daily T-1 ingestion pipeline for a single merchant.

---

## Requirements

### Requirement: Valid Token — No Refresh

The system MUST use an existing bearer token without refreshing it when `(expires_at - now) >= 600s`.
_Source: PRD §2.3; Proposal §OAuth_

#### Scenario: Unexpired token used as-is

- GIVEN a stored token with `expires_at` more than 600 seconds from now
- WHEN the orchestrator prepares the next Otter API call
- THEN the Authorization header carries the stored bearer token
- AND no call is made to `POST /v1/auth/token`

---

### Requirement: Proactive Token Refresh

The system MUST refresh the bearer token BEFORE any resource call when `(expires_at - now) < 600s`.
_Source: PRD §2.3; Proposal §OAuth_

#### Scenario: Token near expiry triggers refresh first

- GIVEN a stored token with `expires_at` exactly 599 seconds from now
- WHEN the orchestrator prepares the next Otter API call
- THEN `POST /v1/auth/token` is called with `grant_type=client_credentials` BEFORE the resource call
- AND the refreshed token replaces the old one in `merchant_credentials`

#### Scenario: Refreshed token persisted

- GIVEN a successful token refresh response `{access_token, expires_in}`
- WHEN the OAuth module writes back credentials
- THEN `SecretsPort.save_credentials()` is called with the new `access_token` and updated `expires_at`
- AND subsequent calls within the same run use the new token

---

### Requirement: 401 Two-Stage Recovery

The system MUST retry once with short backoff on a first 401; if the retry also returns 401, MUST execute `client_credentials` refresh and retry once more.
_Source: Proposal §Resiliency; PRD §7.2_

#### Scenario: Transient 401 resolves on single retry

- GIVEN a resource call returns HTTP 401 on the first attempt
- WHEN the client applies a short backoff and retries
- THEN the second attempt succeeds with HTTP 200
- AND no token refresh grant is issued

#### Scenario: Second 401 triggers token refresh

- GIVEN a resource call returns HTTP 401 twice in a row
- WHEN the second 401 is received
- THEN `POST /v1/auth/token` fires with `grant_type=client_credentials`
- AND the resource call is retried with the new token

#### Scenario: Refresh restores successful call

- GIVEN the token was refreshed after two consecutive 401s
- WHEN the resource call is retried with the new token
- THEN the call succeeds with HTTP 200
- AND the new token is persisted to `merchant_credentials`

---

### Requirement: 429 Exponential Backoff

The system MUST apply exponential backoff with jitter on HTTP 429, up to 3 retries; on the 4th consecutive 429 MUST raise a structured error and log to `pipeline_execution_logs`.
_Source: PRD §2.1 Resiliency Controls; Proposal §Resiliency_

#### Scenario: First 429 triggers backoff and retry

- GIVEN an Otter endpoint returns HTTP 429
- WHEN the client receives the 429
- THEN a jittered exponential wait is applied (base 1s)
- AND the request is retried up to 3 times

#### Scenario: 4th consecutive 429 raises error

- GIVEN all 3 retry attempts also return HTTP 429
- WHEN the 4th consecutive 429 is received
- THEN a structured `RateLimitExceededError` is raised
- AND a failure row is inserted into `pipeline_execution_logs` with `error_class="RateLimitExceededError"`

---

### Requirement: T-1 Daily Window Computation

The orchestrator MUST compute the ingestion window as `[yesterday 00:00:00, yesterday 23:59:59.999999]` in the store's local timezone and pass it to the Otter client.
_Source: PRD §2.1; Proposal §Otter client_

#### Scenario: Window anchored to store local timezone

- GIVEN `merchant_credentials` holds a store timezone of `America/Argentina/Buenos_Aires`
- AND today is 2026-06-10T03:00:00 UTC
- WHEN the orchestrator computes the T-1 window
- THEN `start_date = 2026-06-09T00:00:00-03:00` and `end_date = 2026-06-09T23:59:59.999999-03:00`

#### Scenario: Window passed as query params to GET /v1/orders

- GIVEN the T-1 window is computed
- WHEN `GET /v1/orders` is called
- THEN query params include `start_date` and `end_date` matching the computed window
- AND the `X-Store-Id` header carries the merchant's store ID
- AND the `Authorization: Bearer <token>` header is present

---

### Requirement: Reports Async Job — Enqueue

The system MUST POST to `/v1/reports`, persist the enqueue request body to Bronze, and store the returned `jobId`.
_Source: Proposal §Bronze writer; Proposal §Endpoint Inventory_

#### Scenario: Report enqueue writes manifest to Bronze

- GIVEN a valid bearer token and merchant context
- WHEN `POST /v1/reports` returns `{"jobId": "abc123"}`
- THEN the POST request body (manifest) is written to `s3://.../otter/merchant_id={id}/.../reports_enqueue-{ts}.json`
- AND `jobId="abc123"` is stored for subsequent polling

---

### Requirement: Reports Async Job — Poll to READY

The system MUST poll `GET /v1/reports/{jobId}` until `status=READY` and write the result to Bronze; MUST surface failure if the job fails.
_Source: Proposal §Endpoint Inventory_

#### Scenario: Poll succeeds — result written to Bronze

- GIVEN `GET /v1/reports/{jobId}` first returns `status=PENDING` then `status=READY`
- WHEN the client polls
- THEN the final READY payload is written to `s3://.../otter/merchant_id={id}/.../reports_result-{ts}.json`
- AND both the enqueue manifest and result objects exist as separate S3 keys under the same partition

#### Scenario: Job failure surfaced

- GIVEN `GET /v1/reports/{jobId}` returns `status=FAILED`
- WHEN the client receives the failure status
- THEN a structured `ReportJobFailedError` is raised with the `jobId`

---

### Requirement: Bronze S3 Path Correctness

The system MUST write to `s3://ofae-data-lakehouse-bronze-{env}/otter/merchant_id={merchant_id}/year=YYYY/month=MM/day=DD/{endpoint}-{run_timestamp}.json`.
_Source: PRD §2.2; Proposal §Bronze writer_

**SCN-014 delta (PR2b)**: `build_bronze_key(merchant_id, endpoint, target_date, run_timestamp_utc)` — partition (`year/month/day`) is derived from `target_date` (order/ingestion date); filename timestamp suffix is derived from `run_timestamp_utc` (run instant). `target_date` is REQUIRED.

#### Scenario: Partition path uses target_date, filename uses run_timestamp

- GIVEN `target_date = date(2026,6,9)` and `run_timestamp_utc = datetime(2026,6,10,2,5,0,tzinfo=UTC)`
- WHEN `build_bronze_key("M1", "orders", target_date, run_timestamp_utc)` is called
- THEN the partition path is `year=2026/month=06/day=09` (from `target_date`)
- AND the filename suffix is `orders-20260610T020500Z.json` (from `run_timestamp_utc`)

#### Scenario: Re-run same target_date shares partition, distinct filename

- GIVEN same `target_date=date(2026,6,9)` but `run_timestamp_utc` values of `2026-06-10T02:05:00Z` and `2026-06-10T14:30:00Z`
- WHEN both keys are built
- THEN both share partition `day=09`; filenames differ; distinct S3 objects coexist under the same partition

#### Scenario: Raw unmodified JSON written

- GIVEN the Otter API response body
- WHEN the Bronze writer calls `put_object`
- THEN the S3 object content is byte-for-byte identical to the raw API response
- AND no schema transformation or field removal is applied

---

### Requirement: Multi-Tenant Write Fencing

The system MUST NEVER write a merchant_id=A payload to a path containing merchant_id=B.
_Source: PRD §2.2; Proposal §Bronze writer_

#### Scenario: Merchant A write isolated from Merchant B path

- GIVEN two merchants A and B are both configured
- WHEN the orchestrator runs for merchant A
- THEN ALL S3 `put_object` calls use keys prefixed with `merchant_id=A`
- AND no key prefixed with `merchant_id=B` is written

---

### Requirement: CLI Entrypoint Orchestration

`python -m omc_analytics.ingestion.run --merchant-id <id> --env <env>` MUST orchestrate the full flow and exit non-zero on failure.
_Source: Proposal §Entrypoint_

#### Scenario: Successful run exits zero

- GIVEN valid credentials and a mocked S3/Otter environment
- WHEN the CLI is invoked with `--merchant-id M1 --env dev`
- THEN the process exits with code 0
- AND `pipeline_execution_logs` receives a row with `status=success`, `started_at`, `finished_at`

#### Scenario: Failure exits non-zero

- GIVEN a misconfigured merchant that causes an unrecoverable error
- WHEN the CLI is invoked
- THEN the process exits with a non-zero code
- AND `pipeline_execution_logs` receives a row with `status=failure`, `error_class`, `error_message`

---

### Requirement: SecretsPort Interface Roundtrip

The system MUST load and store credentials through the `SecretsPort` interface; the PR1 implementation MAY use a plaintext stub.
_Source: Proposal §KMS stub; PRD §2.3_

#### Scenario: Credentials loaded via SecretsPort

- GIVEN `SecretsPort` is initialised (stub in PR1)
- WHEN the orchestrator loads merchant credentials
- THEN `SecretsPort.load_credentials(merchant_id)` returns `{access_token, expires_at, public_api_url, store_id}`

#### Scenario: Updated token saved via SecretsPort

- GIVEN a successful token refresh
- WHEN the OAuth module saves back credentials
- THEN `SecretsPort.save_credentials(merchant_id, payload)` is called with the new token data
