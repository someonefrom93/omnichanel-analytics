# Spec: OAuth authorization_code + Typed Errors + Engineering Alerts (PR6a)

> Delta spec. Change: `oauth-errors-alerts-pr6a`. All sections are ADDED (no existing specs).

## ADDED Requirements

### Requirement: exchange_authorization_code

`OAuthRefresher.exchange_authorization_code(code, redirect_uri)` MUST POST a form-encoded body
to `{public_api_url}/v1/auth/token` with `grant_type=authorization_code`, `code`, `redirect_uri`,
`client_id`, `client_secret`. On 200, the response JSON `{access_token, refresh_token?, expires_in,
scope, token_type}` MUST be parsed into a `MerchantCredentials` and persisted via `SecretsPort.save`.
On non-200, MUST raise `OAuthAuthorizationCodeError`.

#### Scenario: Happy path exchange stores creds
- GIVEN a valid `code` and `redirect_uri`
- WHEN `exchange_authorization_code` is called
- THEN the response access_token + refresh_token + expires_at are persisted via SecretsPort

#### Scenario: Response missing refresh_token preserves None
- GIVEN Otter returns `{access_token, expires_in}` without `refresh_token`
- WHEN `exchange_authorization_code` is called
- THEN `MerchantCredentials.refresh_token` is None and creds are still persisted

#### Scenario: Non-200 raises OAuthAuthorizationCodeError
- GIVEN Otter returns 400 or 401
- WHEN `exchange_authorization_code` is called
- THEN `OAuthAuthorizationCodeError` is raised (subclass of `Exception`)

### Requirement: Typed Error Classification in OtterClient

`OtterClient._request_with_401_recovery` SHALL classify errors by HTTP status:
- 3 consecutive 401/403 → raise `Tier1AuthError` (wrapping the original `OtterAPIError`)
- Backoff exhaustion on 429 → raise `Tier2LatencyError` (wrapping `BackoffExhaustedError`)
- Any 5xx → raise `Tier2LatencyError` (wrapping `OtterAPIError`)

`Tier1AuthError` and `Tier2LatencyError` are defined in `ingestion/errors.py`.

#### Scenario: 3 consecutive 401s raise Tier1AuthError
- GIVEN a request path where all retries yield 401
- WHEN `_request_with_401_recovery` exhausts its 401 recovery chain
- THEN `Tier1AuthError` is raised with the triggering status code in its message

#### Scenario: 429 backoff exhaustion raises Tier2LatencyError
- GIVEN 429 responses exhaust the rate-limit retry budget
- WHEN `_request_with_401_recovery` gives up on 429s
- THEN `Tier2LatencyError` is raised

#### Scenario: 5xx raises Tier2LatencyError immediately
- GIVEN a 502 or 503 response from Otter
- WHEN `_request_with_401_recovery` encounters it
- THEN `Tier2LatencyError` is raised (no retry)

### Requirement: AlertsPort Protocol + InMemory + Postgres Implementations

`AlertsPort` Protocol MUST define `insert_alert(alert: EngineeringAlert) -> UUID`.
`EngineeringAlert` Pydantic model SHALL carry: `id: UUID`, `source: str`, `severity: str`,
`error_class: str`, `error_message: str`, `stack_trace: str | None`, `created_at: datetime`.

`InMemoryAlerts` SHALL store alerts in a list; `insert_alert` returns the alert UUID.

`PostgresAlerts` SHALL mirror `PostgresLogs`: injected `connection_factory`, `ThreadedConnectionPool`,
`_acquire` context manager, inserts into `engineering_alerts` table.

#### Scenario: InMemoryAlerts round-trip
- GIVEN an `EngineeringAlert`
- WHEN `insert_alert(alert)` is called
- THEN the returned UUID matches `alert.id` and the alert is retrievable

#### Scenario: PostgresAlerts insert via connection pool
- GIVEN a psycopg2 connection factory with the `engineering_alerts` table created
- WHEN `insert_alert(alert)` is called
- THEN a row is committed with matching id, source, severity, error_class, error_message

### Requirement: Migration 003 — engineering_alerts DDL

DDL `003_create_engineering_alerts.sql` MUST `CREATE TABLE IF NOT EXISTS engineering_alerts` with:
`id UUID PRIMARY KEY`, `source TEXT NOT NULL`, `severity TEXT NOT NULL`, `error_class TEXT NOT NULL`,
`error_message TEXT NOT NULL`, `stack_trace TEXT`, `created_at TIMESTAMPTZ NOT NULL`.
A named index on `(created_at DESC)` MUST be created if not exists.

#### Scenario: Table is idempotent
- GIVEN the DDL is executed twice
- WHEN the second execution runs
- THEN no error is raised (IF NOT EXISTS guard)

#### Scenario: Alert insert and query by severity
- GIVEN a row inserted with `severity = 'error'`
- WHEN `SELECT * FROM engineering_alerts WHERE severity = 'error'`
- THEN one row is returned with the expected fields

### Requirement: alerts_factory in config.py

`alerts_factory(ctx: RunContext, connection_factory=None) -> AlertsPort` SHALL return:
- `InMemoryAlerts` when `OMCAE_ALERTS_BACKEND` env var is `memory` (default).
- `PostgresAlerts` when `OMCAE_ALERTS_BACKEND=postgres` and `connection_factory` is provided.
- MUST raise `ConfigError` if `postgres` is selected but `connection_factory` is `None`.

`RunContext` MUST gain an `alerts_backend: str = "memory"` field (populated from env var).

#### Scenario: Default is InMemoryAlerts
- GIVEN `OMCAE_ALERTS_BACKEND` is unset
- WHEN `alerts_factory(ctx)` is called
- THEN an `InMemoryAlerts` instance is returned

#### Scenario: Postgres backend with valid connection_factory
- GIVEN `OMCAE_ALERTS_BACKEND=postgres` and a valid `connection_factory`
- WHEN `alerts_factory(ctx, connection_factory=factory)` is called
- THEN a `PostgresAlerts` instance is returned

#### Scenario: Postgres backend without connection_factory raises ConfigError
- GIVEN `OMCAE_ALERTS_BACKEND=postgres` and `connection_factory=None`
- WHEN `alerts_factory(ctx)` is called
- THEN `ConfigError` is raised
