# Design: Scaffold Bronze Ingestion (PR1)

## Technical Approach

Stand up the `omc_analytics` Python package and implement the daily T-1 ingestion slice per the approved proposal + both specs: Otter HTTP client (4 endpoints) with two-stage 401 recovery and 429 exponential backoff, OAuth token refresher with a 10-minute pre-expiry check, and a boto3-backed Bronze S3 writer that puts raw JSON under a Hive `merchant_id=` partition. Hexagonal layering — every external dep (HTTP, S3, secrets, logs) is injected via Protocol, so the strict TDD flow can substitute fakes. Reports are dual-written (enqueue manifest + final job result) as separate S3 objects under the same partition.

This is the first vertical slice of OFAE (PRD §1.2) and unblocks PR2 (dbt Silver/Gold, real KMS, COGS, Streamlit).

## Architecture Decisions

### Decision: Hexagonal layering with Protocol ports

**Choice**: Inject `requests.Session`, boto3 S3 client, `SecretsPort`, and `LogsPort` into `OtterClient` / `BronzeWriter` / orchestrator.
**Rationale**: TDD requires determinism and no live network/AWS. Protocol ports are the swap point for PR2 (real Postgres-backed `LogsPort`, real KMS-backed `SecretsPort`) without touching call sites.
**Tradeoff accepted**: Slight indirection cost; the spec demands PR1 tests never hit real services, so this is non-negotiable.

### Decision: 401 recovery is a single decorator/middleware on the client

**Choice**: A `_with_401_recovery(self, fn)` wrapper applied to every public `OtterClient` method. The wrapper owns the "retry once with short backoff → refresh → retry once more" loop, so call sites (orders, reports POST/GET) stay free of 401 logic.
**Rationale**: PRD §7.2 demands the exact sequence `401 → 401 → 200` validates a token refresh. Duplicating the loop in each method would let them drift.

### Decision: 429 backoff and 401-retry backoff share one `RetryPolicy`

**Choice**: A single `RetryPolicy(max_retries, base, cap, jitter=True)` class. `OtterClient` uses one instance for 429; the 401-retry path uses a second instance with a fixed tiny base (e.g. 0.5s).
**Rationale**: One jittered-exponential helper, two configurations. The report poller has its own schedule (locked decision below) but reuses the same exponential helper.
**Alternative rejected**: Two independent `time.sleep(N)` calls scattered in the client — untestable, and the proposal's forecast budget assumes a shared `backoff.py` module.

### Decision: Reports dual-write is a thin wrapper, not a separate writer

**Choice**: `BronzeWriter.write_raw(merchant_id, endpoint, payload, run_timestamp)` is the single primitive. The reports path is a `write_report_pair(merchant_id, request_body, result_payload, run_timestamp)` wrapper that calls `write_raw(..., endpoint="reports_enqueue", ...)` then `write_raw(..., endpoint="reports_result", ...)`.
**Rationale**: Same byte-for-byte guarantee (spec: "raw unmodified JSON"); no schema divergence between orders/reports paths; the manifest object is just the request body, kept minimal to stay under the 400-line budget.

### Decision: Path construction is a pure function

**Choice**: `build_bronze_key(merchant_id, endpoint, run_timestamp_utc) -> str` is a module-level pure function in `bronze_writer.py`. `BronzeWriter.write_raw` calls it then `put_object`s.
**Rationale**: Pure functions are trivially testable (input → expected key) and reusable for PR2 backfill which writes many objects per run. Keeps the writer class thin.

### Decision: T-1 window computed once in the orchestrator

**Choice**: `compute_t1_window(store_tz: ZoneInfo, now_utc: datetime) -> tuple[datetime, datetime]` lives in `ingestion.run` (or a small `ingestion/window.py` helper if it grows). The client receives `(start, end)` as args.
**Rationale**: The Otter client stays reusable for PR2 backfill (any window, not just T-1). Matches the proposal's resolved fork.

### Decision: Stub `LogsPort` is the swap point, not a real DB

**Choice**: In-memory list + Protocol with `insert_started(row) -> run_id` and `update_finished(run_id, status, error_class, error_message)`. Schema locked (see "Locked decisions"). PR2 swaps the in-memory impl for a Postgres-backed one without changing the orchestrator.

### Decision: Stub `SecretsPort` returns plaintext in PR1

**Choice**: `SecretsPort.load_credentials(merchant_id) -> dict` and `save_credentials(merchant_id, payload) -> None`. The dev stub holds a JSON file or in-memory dict. KMS envelope encryption is PR2.
**Rationale**: Keeps PR1 under 400 lines; isolates KMS IAM to PR2 (proposal §KMS stub).

## Module Layout

```
src/omc_analytics/
├── __init__.py
├── common/
│   ├── __init__.py
│   ├── config.py        # RunContext dataclass, env/CLI parsing (click + pydantic)
│   ├── logging.py       # structlog-style JSON line logger; run_id bound context
│   └── secrets.py       # SecretsPort Protocol + dev stub impl
├── ingestion/
│   ├── __init__.py
│   ├── otter_client.py  # OtterClient class + _with_401_recovery wrapper
│   ├── oauth.py         # OAuthRefresher (client_credentials grant)
│   ├── backoff.py       # RetryPolicy (jittered exponential)
│   ├── bronze_writer.py # BronzeWriter + build_bronze_key (pure) + write_report_pair
│   └── run.py           # CLI entrypoint + T-1 window + orchestration
├── transformation/     # (empty placeholder for PR2)
└── serving/            # (empty placeholder for PR2)
```

`transformation/` and `serving/` exist as empty `__init__.py` only — keeps the layout honest with the proposal and the PRD's medallion mental model, but ships zero LOC.

## Data Flow

```
CLI: python -m omc_analytics.ingestion.run --merchant-id M1 --env dev
        │
        ▼
ingestion.run.build_run_context()  ──► RunContext(merchant_id, env, run_id, s3_bucket, ...)
        │
        ▼
secrets.load_credentials(M1)  ──► SecretsPort stub  ──► {access_token, expires_at, public_api_url, store_id, store_tz}
        │
        ▼
oauth.OAuthRefresher.maybe_refresh(creds)  ──► if (expires_at - now) < 600s → POST /v1/auth/token
        │                                       (grant_type=client_credentials)
        │                                       save_credentials(M1, new_creds)
        ▼
ingestion.run.compute_t1_window(store_tz, now_utc)  ──► (start, end)
        │
        ▼
logs.insert_started(row)  ──► LogsPort stub  ──► in-memory list
        │
        ▼
OtterClient.fetch_orders(start, end, store_id)  ──► GET /v1/orders  [wrapped: 429 backoff + 401 recovery]
        │
        ▼
BronzeWriter.write_raw(M1, "orders", body, run_ts)  ──► s3://.../otter/merchant_id=M1/year=.../day=.../orders-{run_ts}.json
        │
        ▼
[for reports] OtterClient.request_report(...) ──► write_raw(..., "reports_enqueue", request_body, run_ts)
              OtterClient.poll_report(job_id)   ──► write_raw(..., "reports_result", final_payload, run_ts)
        │
        ▼
logs.update_finished(run_id, "SUCCESS", None, None)
        │
        ▼
exit 0
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Create | uv-managed Python 3.12; deps per proposal |
| `src/omc_analytics/__init__.py` | Create | Empty |
| `src/omc_analytics/common/__init__.py` | Create | Empty |
| `src/omc_analytics/common/config.py` | Create | `RunContext` dataclass, env/CLI parsing (click + pydantic) |
| `src/omc_analytics/common/logging.py` | Create | JSON-line logger, `run_id` contextvar |
| `src/omc_analytics/common/secrets.py` | Create | `SecretsPort` Protocol + dev stub |
| `src/omc_analytics/ingestion/__init__.py` | Create | Empty |
| `src/omc_analytics/ingestion/otter_client.py` | Create | `OtterClient` + `_with_401_recovery` wrapper |
| `src/omc_analytics/ingestion/oauth.py` | Create | `OAuthRefresher` |
| `src/omc_analytics/ingestion/backoff.py` | Create | `RetryPolicy` |
| `src/omc_analytics/ingestion/bronze_writer.py` | Create | `BronzeWriter` + `build_bronze_key` (pure) + `write_report_pair` |
| `src/omc_analytics/ingestion/run.py` | Create | CLI entrypoint + orchestration |
| `src/omc_analytics/transformation/__init__.py` | Create | Empty placeholder |
| `src/omc_analytics/serving/__init__.py` | Create | Empty placeholder |
| `tests/conftest.py` | Create | `responses`/`moto` fixtures, fixture loaders |
| `tests/unit/ingestion/test_otter_client.py` | Create | 401 two-stage, 429 backoff, happy path, header assertions |
| `tests/unit/ingestion/test_oauth.py` | Create | Pre-expiry refresh, no-op when fresh, write-back |
| `tests/unit/ingestion/test_backoff.py` | Create | Exponential growth, jitter range, exhaustion at N+1 |
| `tests/unit/ingestion/test_bronze_writer.py` | Create | Key shape, run-timestamp filename, fencing |
| `tests/unit/ingestion/test_run.py` | Create | Orchestration, exit codes, log row writes |
| `tests/integration/test_bronze_s3.py` | Create | moto-S3 end-to-end via the CLI |
| `tests/fixtures/otter/orders_sample.json` | Create | ReDoc-derived, tagged `{source: redoc-sample, version: 1.0}` |
| `tests/fixtures/otter/oauth_token_sample.json` | Create | ReDoc-derived |
| `tests/fixtures/otter/reports_enqueue_sample.json` | Create | ReDoc-derived |
| `tests/fixtures/otter/reports_result_sample.json` | Create | ReDoc-derived |

All changes are additive (greenfield). No deletions.

## Interfaces / Contracts

```python
# common/config.py
@dataclass(frozen=True)
class RunContext:
    merchant_id: str
    env: Literal["dev", "prod"]
    run_id: UUID                 # generated per CLI invocation
    run_timestamp_utc: datetime  # fixed at CLI start, passed to writer
    s3_bucket: str               # from env: f"ofae-data-lakehouse-bronze-{env}"

def build_run_context(merchant_id: str, env: str) -> RunContext: ...

# common/secrets.py
class SecretsPort(Protocol):
    def load_credentials(self, merchant_id: str) -> dict: ...
    def save_credentials(self, merchant_id: str, payload: dict) -> None: ...

class InMemorySecrets:  # PR1 stub
    ...

# common/logging.py
def get_logger(run_id: UUID) -> Logger: ...

# ingestion/otter_client.py
class OtterClient:
    def __init__(self, session: requests.Session, base_url: str, store_id: str,
                 token_provider: Callable[[], str], on_token_refresh: Callable[[str, int], None],
                 retry_policy: RetryPolicy): ...
    def fetch_orders(self, start: datetime, end: datetime) -> dict: ...
    def request_report(self, body: dict) -> str: ...  # returns jobId
    def poll_report(self, job_id: str) -> dict: ...   # uses ReportPoller schedule

# ingestion/oauth.py
class OAuthRefresher:
    def __init__(self, session: requests.Session, secrets: SecretsPort, merchant_id: str): ...
    def maybe_refresh(self, creds: dict) -> dict: ...   # 10-min pre-expiry check
    def force_refresh(self) -> dict: ...

# ingestion/backoff.py
@dataclass
class RetryPolicy:
    max_retries: int             # 3 for 429, 1 for 401-retry
    base_seconds: float
    cap_seconds: float = 60.0
    jitter: bool = True
    def wait_for(self, attempt: int) -> float: ...     # pure: returns sleep seconds
    def should_retry(self, attempt: int) -> bool: ...

# ingestion/bronze_writer.py
def build_bronze_key(merchant_id: str, endpoint: str, run_timestamp_utc: datetime) -> str: ...

class BronzeWriter:
    def __init__(self, s3_client, bucket: str): ...
    def write_raw(self, merchant_id: str, endpoint: str, payload: bytes | str, run_timestamp_utc: datetime) -> str: ...
    def write_report_pair(self, merchant_id: str, request_body: dict, result_payload: dict, run_timestamp_utc: datetime) -> tuple[str, str]: ...

# ingestion/run.py  (LogsPort — locked schema)
class LogsPort(Protocol):
    def insert_started(self, row: dict) -> str: ...   # returns run_id echo
    def update_finished(self, run_id: str, status: Literal["STARTED","SUCCESS","FAILED"],
                        error_class: str | None, error_message: str | None) -> None: ...

class InMemoryLogs: ...   # PR1 stub, list-backed
```

## Configuration Loading

CLI (click) accepts `--merchant-id` (required) and `--env` (required, `dev`|`prod`). `build_run_context` reads `OMCAE_PG_DSN` (unused in PR1, validated for presence) and the standard boto3 creds chain. The S3 bucket is derived: `f"ofae-data-lakehouse-bronze-{env}"`. `run_id` (UUID4) and `run_timestamp_utc` (frozen at CLI start) are generated here and threaded through the orchestrator. The store timezone lives in `merchant_credentials.store_tz` (IANA name, e.g. `America/Argentina/Buenos_Aires`); the orchestrator uses `zoneinfo.ZoneInfo` to compute T-1.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `build_bronze_key` shape & fencing | Pure function; parametrize inputs |
| Unit | `RetryPolicy.wait_for` | Assert growth, cap, jitter range; freeze time |
| Unit | `OAuthRefresher.maybe_refresh` pre-expiry | Clock at 599s, 600s, 601s boundaries |
| Unit | `OtterClient` 401 → 401 → 200 | `responses` queue of 3 responses; assert call count + token rotation |
| Unit | `OtterClient` 429 × 3 → 200 | `responses` queue; assert sleep sequence via `freezegun` |
| Unit | `OtterClient` 429 × 4 → `RateLimitExceededError` | `responses` queue; assert exception + log row |
| Unit | `OtterClient` 401 once → success on retry | Distinct from two-stage case |
| Unit | `BronzeWriter.write_raw` byte-identity | moto-S3; `get_object` body == input |
| Unit | Orchestrator exit codes + log rows | Inject in-memory `LogsPort`; assert rows |
| Integration | End-to-end CLI against moto + `responses` | `subprocess` or `CliRunner`; assert S3 keys + log rows |

**Strict TDD flow** (per `config.yaml` `apply.tdd: true`): for each module, write the failing test first (RED), then the minimum implementation to pass (GREEN), then refactor. The 22 files from the proposal's per-file breakdown map 1:1 to test files + impl files. Coverage threshold: ≥ 80% on `src/omc_analytics/ingestion/` (proposal success criterion; `verify.coverage_threshold: 80`).

## Migration / Rollout

No migration required. PR1 is additive (no DB schema, no existing readers). Rollback = revert PR + `aws s3 rm s3://ofae-data-lakehouse-bronze-{env}/otter/merchant_id=<id>/ --recursive` + `uv remove` of added deps (proposal §Rollback).

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Otter API drifts from ReDoc samples | Med | Fixtures tagged `source: redoc-sample`; CI never hits live API; update on bump |
| `responses` library version pin drift | Low | Lock in `pyproject.toml`; CI matrix pinned to `responses==0.25.x` |
| 400-line budget creep on report dual-write | Med | Manifest kept minimal (POST body echo); single primitive `write_raw` |
| S3 KMS permissions in dev | Med | `moto[s3]` for tests; no real AWS in CI |
| `freezegun` + real `time.sleep` interplay in 429 tests | Low | `RetryPolicy.wait_for` is pure; tests assert the return value, not real sleeps |
| Public API base URL varies per merchant | Low | `merchant_credentials.public_api_url` validated at `load_credentials`; CLI errors loudly if blank |

## Open Questions

None — all blocking questions were resolved before this phase (see Locked decisions below). Non-blocking follow-ups deferred to PR2: real KMS round-trip, real Postgres `pipeline_execution_logs` schema, backfill loop, cron wiring.

## Locked decisions (resolved from sdd-spec open questions)

### Decision: `pipeline_execution_logs` stub schema (PR1 stub, real schema in PR2)

**Locked schema** (the `LogsPort` interface is the swap point; PR2 swaps the in-memory impl for a real PostgreSQL-backed one without changing the orchestrator):

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID v4 | client-side generated |
| `merchant_id` | str | FK to `merchant_credentials` |
| `run_id` | UUID v4 | generated per CLI invocation |
| `pipeline_name` | str | constant `"otter_bronze_ingestion"` in PR1 |
| `status` | enum | `STARTED` \| `SUCCESS` \| `FAILED` |
| `started_at` | datetime | UTC, ISO-8601 |
| `finished_at` | datetime | UTC, ISO-8601; nullable while `STARTED` |
| `error_class` | str | nullable; e.g. `"RateLimitExceededError"`, `"ReportJobFailedError"`, `"OtterAPIError"`, `"BackoffExhausted"` |
| `error_message` | str | nullable; free text |

`LogsPort` interface: `insert_started(row) -> str` and `update_finished(run_id, status, error_class, error_message)`. Tests couple to the interface, not the storage.

### Decision: Report polling ceiling (`GET /v1/reports/{jobId}`)

**Locked schedule for PR1**:
- Max 10 poll attempts
- Initial delay 2s, exponential base 2 → 2s, 4s, 8s, 16s, 32s, 60s cap, 60s cap, 60s cap, 60s cap, 60s cap
- Total max wall time ≈ 7 minutes
- Terminal states:
  - `READY` → return payload, success
  - `FAILED` → raise `ReportJobFailedError(job_id)`
  - `CANCELLED` → raise `ReportJobCancelledError(job_id)`
  - Unknown status codes → treat as transient, re-poll
- Surfaced as a `ReportPoller` class (sibling of `OtterClient` or nested inside it) so PR2 can swap the schedule without touching call sites

The 401-retry path inside `poll_report` reuses the same `RetryPolicy` instance configured for 1 retry + short base; the poll *schedule* is independent of the per-call retry policy. They do not share the same schedule.
