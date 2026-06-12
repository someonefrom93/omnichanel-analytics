# Design: OAuth authorization_code + Typed Errors + Engineering Alerts (PR6a)

## Technical Approach

Three independent capabilities layered into existing modules, zero new dependencies:
1. `ingestion/oauth.py`: add `exchange_authorization_code` — mirrors `request_initial_token` pattern
   (form-encoded POST → parse JSON → `model_copy` → `secrets.save`).
2. `ingestion/otter_client.py`: classify terminal failures as `Tier1AuthError` / `Tier2LatencyError`
   at the `_request_with_401_recovery` return points.
3. `common/alerts.py`: `AlertsPort` Protocol + `InMemoryAlerts` + `PostgresAlerts` — mirrors
   `LogsPort`/`PostgresLogs` architecture exactly.
4. `common/config.py`: `alerts_factory` — mirrors `logs_factory` pattern.
5. DDL `003_create_engineering_alerts.sql` — mirrors `001_create_pipeline_execution_logs.sql`.

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Typed error hierarchy | `Tier1AuthError(Exception)`, `Tier2LatencyError(Exception)` — thin wrappers | No shared base; classification happens at raise site. PR6b's `classify()` catches by type |
| OtterClient error wrap sites | Wrap at the exception raise points (3rd 401 → Tier1AuthError, backoff exhausted → Tier2LatencyError, 5xx → Tier2LatencyError) | Single responsibility: OtterClient owns HTTP error semantics |
| AlertsPort shape | `insert_alert(alert: EngineeringAlert) -> UUID` only (no update_finished) | Alerts are append-only immutable records; no lifecycle |
| PostgresAlerts architecture | Mirrors PostgresLogs: injected `connection_factory`, `ThreadedConnectionPool`, `_acquire` ctx mgr | Proven pattern from PR2a; tested; zero new architecture |
| Factory env var | `OMCAE_ALERTS_BACKEND` (separate from `OMCAE_LOGS_BACKEND`) | Independent backends; alerts table ≠ pipeline_execution_logs table |
| RunContext field | `alerts_backend: str = "memory"` mirroring `secrets_backend`/`logs_backend` | Consistent pattern; env var read in `_read_env_defaults` |

## Data Flow

```
OtterClient._request_with_401_recovery
  ├─ 3rd 401 → Tier1AuthError  ← (ingestion/errors.py)
  ├─ 429 exhaustion → Tier2LatencyError
  └─ 5xx → Tier2LatencyError

alerts_factory(ctx, connection_factory)
  ├─ OMCAE_ALERTS_BACKEND=memory → InMemoryAlerts
  └─ OMCAE_ALERTS_BACKEND=postgres → PostgresAlerts(connection_factory)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/omc_analytics/ingestion/errors.py` | Modify | +`Tier1AuthError`, `Tier2LatencyError`, `OAuthAuthorizationCodeError` |
| `src/omc_analytics/ingestion/oauth.py` | Modify | +`exchange_authorization_code(code, redirect_uri)` on `OAuthRefresher` |
| `src/omc_analytics/ingestion/otter_client.py` | Modify | Classify terminal 401 as Tier1AuthError; 5xx/429 exhaustion as Tier2LatencyError |
| `src/omc_analytics/common/alerts.py` | **Create** | `AlertsPort` Protocol, `EngineeringAlert` model, `InMemoryAlerts`, `PostgresAlerts` |
| `src/omc_analytics/common/migrations/003_create_engineering_alerts.sql` | **Create** | DDL: id, source, severity, error_class, error_message, stack_trace, created_at + index |
| `src/omc_analytics/common/config.py` | Modify | +`alerts_factory(ctx, connection_factory=None)`, +`alerts_backend` field on `RunContext` |
| `src/omc_analytics/serving/streamlit_app.py` | Modify | Connection-status micro-indicator placeholder (read-only, uses OAuthRefresher stub) |
| `tests/unit/ingestion/test_oauth.py` | Modify | +`TestExchangeAuthorizationCode` (3 cases) |
| `tests/unit/ingestion/test_otter_client.py` | Modify | +typed error classification cases |
| `tests/unit/common/test_alerts.py` | **Create** | InMemoryAlerts round-trip, EngineeringAlert validation |
| `tests/unit/common/test_alerts_postgres.py` | **Create** | PostgresAlerts with testcontainers |
| `tests/unit/common/test_config_factory.py` | Modify | +`test_alerts_factory_*` cases |
| `tests/unit/common/test_migration_ddl.py` | Modify | +`test_003_engineering_alerts_ddl` |

## Interfaces / Contracts

```python
# AlertsPort Protocol
class AlertsPort(Protocol):
    def insert_alert(self, alert: EngineeringAlert) -> UUID: ...

# EngineeringAlert Pydantic model
class EngineeringAlert(BaseModel):
    id: UUID
    source: str
    severity: str
    error_class: str
    error_message: str
    stack_trace: str | None = None
    created_at: datetime
```

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | `exchange_authorization_code` 3 cases | `responses` mock, InMemorySecrets, verify SecretsPort.save called |
| Unit | Typed error classification 4 cases | Mock responses at OtterClient level; assert exception type and message |
| Unit | InMemoryAlerts round-trip | Insert alert, verify retrievable from internal list |
| Unit | PostgresAlerts | `testcontainers.postgres`, DDL 003 applied, insert + query |
| Unit | alerts_factory 3 cases | Env var isolation via `monkeypatch` |
| Unit | DDL 003 idempotency | Execute twice, verify no error |
| Integration | OAuth + typed errors + alerts wiring | `test_pr6a_integration.py` (optional per ~500 LOC budget) |

## Migration / Rollout

No data migration required. DDL is `CREATE TABLE IF NOT EXISTS` (idempotent).
Rollback: drop `engineering_alerts` table; remove `alerts_factory` from config.
Typed errors are wrappers around existing exceptions — no behavioral change to callers.

## Open Questions

- [ ] None. All decisions locked per umbrella proposal.
