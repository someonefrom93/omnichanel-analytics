# Tasks: OAuth authorization_code + Typed Errors + Alerts (PR6a)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~480 LOC |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Phase 1: Typed Errors + OtterClient Classification

- [ ] 1.1 Add `Tier1AuthError`, `Tier2LatencyError`, `OAuthAuthorizationCodeError` to `ingestion/errors.py`
- [ ] 1.2 Wrap 3rd-consecutive-401 in OtterClient._request_with_401_recovery as Tier1AuthError
- [ ] 1.3 Wrap 429 backoff exhaustion as Tier2LatencyError in OtterClient
- [ ] 1.4 Wrap 5xx (500-599) as Tier2LatencyError in OtterClient
- [ ] 1.5 Unit tests: verify correct exception type raised for each classified path

## Phase 2: exchange_authorization_code

- [ ] 2.1 Add `exchange_authorization_code(code, redirect_uri) -> MerchantCredentials` to `OAuthRefresher`
- [ ] 2.2 Unit tests: happy path (persists access_token + refresh_token + expires_at)
- [ ] 2.3 Unit test: missing refresh_token in response → preserves None
- [ ] 2.4 Unit test: non-200 → raises OAuthAuthorizationCodeError

## Phase 3: AlertsPort + InMemoryAlerts

- [ ] 3.1 Define `EngineeringAlert` Pydantic model and `AlertsPort` Protocol in `common/alerts.py`
- [ ] 3.2 Implement `InMemoryAlerts` (list-backed, mirrors InMemoryLogs)
- [ ] 3.3 Unit tests: insert + retrieve round-trip, model validation

## Phase 4: PostgresAlerts + DDL 003

- [ ] 4.1 Write `common/migrations/003_create_engineering_alerts.sql` (mirrors 001 pattern)
- [ ] 4.2 Implement `PostgresAlerts` (mirrors PostgresLogs: connection_factory, pool, _acquire)
- [ ] 4.3 Unit test: DDL idempotency (CREATE IF NOT EXISTS run twice)
- [ ] 4.4 Unit test: PostgresAlerts insert + query via testcontainers

## Phase 5: alerts_factory + Integration

- [ ] 5.1 Add `alerts_backend` field to `RunContext`, read `OMCAE_ALERTS_BACKEND` in `_read_env_defaults`
- [ ] 5.2 Implement `alerts_factory(ctx, connection_factory=None)` in `config.py`
- [ ] 5.3 Unit tests: default InMemory, postgres with factory, postgres without factory → ConfigError
- [ ] 5.4 Integration: wire alerts_factory into run.py, verify Tier3 alerts flow end-to-end
- [ ] 5.5 Update `streamlit_app.py` sidebar with connection-status micro-indicator placeholder
