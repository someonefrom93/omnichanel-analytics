# Local Test Mocking Specification

> Source: PRD §7.1, §7.2 · Proposal: Scaffold Bronze Ingestion (PR1) §Test layer
> Scope: PR1 only — live API calls, CI secrets, and real AWS resources are out of scope.

## Purpose

Define the observable behaviour of the `responses`-based mock layer and ReDoc-derived fixture set used to intercept Otter API HTTP calls and AWS S3 writes during `pytest` runs, ensuring CI never contacts live endpoints.

---

## Requirements

### Requirement: No Live Network Calls During pytest

The test suite MUST NOT make real HTTP calls to the Otter API or real AWS API calls during `pytest`.
_Source: PRD §7.1; Proposal §Test layer; Proposal §Success Criteria_

#### Scenario: All Otter HTTP calls intercepted by responses

- GIVEN the `responses` library activates its mock context
- WHEN any Otter endpoint URL matching `*/v1/*` is called
- THEN the call is served by a registered fixture response
- AND no TCP connection to `api.tryotter.com` is opened

#### Scenario: All S3 operations handled by moto

- GIVEN `moto[s3]` mocks the S3 service
- WHEN `bronze_writer.put_object()` is called
- THEN the call is handled in-memory by moto
- AND no real AWS S3 API call is made

---

### Requirement: ReDoc-Derived Fixtures

Fixture files MUST be stored under `tests/fixtures/otter/` and tagged with `{"source": "redoc-sample", "version": "1.0"}`.
_Source: Proposal §Test layer_

#### Scenario: Fixture files present and tagged

- GIVEN the test suite is set up
- WHEN `tests/fixtures/otter/orders_sample.json`, `oauth_token_sample.json`, `reports_enqueue_sample.json`, `reports_result_sample.json` are loaded
- THEN each file's top-level metadata contains `"source": "redoc-sample"` and `"version": "1.0"`

#### Scenario: Fixture shape matches API contract

- GIVEN the `orders_sample.json` fixture
- WHEN a test parses it
- THEN it contains at least one order object with the fields documented in the Otter Public API reference

---

### Requirement: 401 Loop Simulation

The mock layer MUST support programming a sequence of HTTP 401 → 401 → 200 to validate the two-stage refresh flow.
_Source: PRD §7.2; Proposal §Resiliency_

#### Scenario: Sequential 401 → 401 → 200 mock sequence

- GIVEN a `responses` mock configured to return 401 twice then 200 for the same URL
- WHEN the Otter client executes the request
- THEN the first call receives 401, triggering retry
- AND the second call receives 401, triggering token refresh
- AND the third call receives 200, completing successfully

---

### Requirement: 429 Backoff Simulation

The mock layer MUST support programming N consecutive 429 responses followed by optional success, to validate exponential backoff and max-retry exhaustion.
_Source: PRD §7.2; Proposal §Resiliency_

#### Scenario: 3 consecutive 429s then success

- GIVEN a mock returning 429 three times then 200
- WHEN the backoff module handles responses
- THEN three exponential waits are applied (base 1s, jittered)
- AND the fourth call receives 200 and succeeds

#### Scenario: 4 consecutive 429s exhausts retries

- GIVEN a mock returning 429 four times
- WHEN the backoff module handles responses
- THEN `RateLimitExceededError` is raised after the 4th 429
- AND no further retry is attempted
