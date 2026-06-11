# Proposal: Scaffold Bronze Ingestion (PR1)

## Intent

Stand up the Python package + Otter client against the documented Public API
(https://developer-guides.tryotter.com/api-reference/) with OAuth + 429 backoff,
write raw JSON into the S3 Bronze tier with Hive multi-tenant fencing, and run a
T-1 store-local daily entrypoint. First vertical slice of OFAE (PRD §1.2).
Downstream layers (dbt, Streamlit, COGS) are out of scope.

## Scope

### In Scope
- **Package scaffold** — `src/omc_analytics/{ingestion,transformation,serving,common}/`; `pyproject.toml` (uv) with `requests`, `boto3`, `cryptography`, `psycopg2-binary`, `click`, `pytest`, `responses`, `moto[s3]`, `freezegun`, `ruff`, `mypy`, `black`.
- **Otter client** (`ingestion.otter_client`) — three endpoints (see inventory below); daily window `yesterday_00:00:00..yesterday_23:59:59` store-local computed by orchestrator.
- **Resiliency** — HTTP 429 exponential backoff (max 3 retries, base 1s, jittered). HTTP 401: single retry with short backoff first (docs note transient internal auth glitches), then fall back to OAuth token refresh on second 401.
- **OAuth** (`ingestion.oauth`) — `grant_type=client_credentials` (server-to-server) for PR1; `authorization_code` flow deferred to OAuth wizard PR. Refresh when `(expires_at - now) < 600s`; write back to `merchant_credentials`.
- **Bronze writer** (`ingestion.bronze_writer`) — boto3 `put_object` → `s3://ofae-data-lakehouse-bronze-{env}/otter/merchant_id=[id]/year=YYYY/month=MM/day=DD/<endpoint>-{ts}.json`. For reports (async job pattern), store BOTH the enqueue POST body (request manifest) AND the final job result so PR2's Silver layer can re-derive joins.
- **Entrypoint** (`ingestion.run`) — `python -m omc_analytics.ingestion.run --merchant-id <id> --env <env>`: creds → refresh → fetch T-1 → write Bronze → log to `pipeline_execution_logs` (stub insert).
- **Test layer** — `responses` library; fixtures under `tests/fixtures/otter/` derived from ReDoc samples on developer-guides.tryotter.com; CI never calls the live Public API. Fixtures carry `{"source": "redoc-sample", "version": "1.0"}`.

### Out of Scope (PR2+)
dbt + Silver/Gold; `merchant_cogs` + Streamlit UI; full KMS envelope encryption (`SecretsPort` interface stubbed only in PR1); 30-day backfill loop; cron wiring; real `pipeline_execution_logs` schema; Tier 1/2/3 user banners; authorization_code OAuth flow; webhooks.

## Endpoint Inventory

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| POST | `/v1/auth/token` | n/a (auth) | Generate bearer token via `client_credentials` grant. Form body: `grant_type`, `client_id`, `client_secret`, `scope`. Returns `{access_token, expires_in (~30d), scope, token_type}`. |
| GET | `/v1/orders` | `orders.read` | Fetch order feed for a store. Query params: `start_date`, `end_date`. Header: `X-Store-Id`. |
| POST | `/v1/reports` | `reports.generate_report` | Request async business report. Returns `{jobId}`. |
| GET | `/v1/reports/{jobId}` | `reports.generate_report` | Poll job status until `READY`, then fetch result payload. |

**Per-tenant base URL**: `{{public-api-url}}` is merchant-specific (not a global env var). Stored per-row in `merchant_credentials.public_api_url`, encrypted at rest via KMS through `SecretsPort`.

## Capabilities

### New Capabilities
- `bronze-ingestion`: package + Otter client (4 endpoints) + Bronze writer + T-1 orchestrator. Covers PRD §2.1, §2.2, §2.3.
- `local-test-mocking`: `responses`-based mock layer with ReDoc-derived fixtures, reusable across future ingestion tests.

### Modified Capabilities
- None (greenfield; `openspec/specs/` is empty).

## Approach

- **Strict TDD** per `apply.tdd: true` — RED → GREEN → REFACTOR per module.
- **Hexagonal layering**: clients accept injected `requests.Session` + boto3 client; tests substitute fakes.
- **Time-window discipline**: window computed once in orchestrator, passed in. Keeps client reusable for PR2 backfill.
- **KMS stub**: `SecretsPort.decrypt_credentials()` returns plaintext in dev; PR2 swaps impl.
- **401 two-stage**: retry once (docs confirm transient internal glitches), then refresh token. Prevents thrashing.
- **Report dual-write**: `bronze_writer` writes enqueue manifest + final job result as separate S3 objects under same partition prefix.

## Design Forks Resolved (from sdd/scaffold-bronze-ingestion/explore)

| Fork | Options | Chosen | Rationale |
|---|---|---|---|
| HTTP mocking lib | `responses` / `requests-mock` | `responses` | Sentry-maintained; `json_params_matcher` + `assert_call_count`; lower fixture code. |
| Time-window compute | Client / orchestrator | Orchestrator | Reusable for PR2 backfill; client stays dumb. |
| KMS in PR1 | Full / stub | Stub `SecretsPort` | Keeps PR1 < 400 lines; isolates KMS IAM to PR2. |

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `pyproject.toml` | New | uv-managed Python 3.12, dev + prod deps |
| `src/omc_analytics/common/{config,logging,secrets}.py` | New | Env config, logging, secrets stub with `public_api_url` support |
| `src/omc_analytics/ingestion/{otter_client,oauth,backoff,bronze_writer,run}.py` | New | Five production modules |
| `tests/fixtures/otter/{orders,reports_enqueue,reports_result,oauth_token}.json` | New | ReDoc-derived API response samples |
| `tests/unit/ingestion/` + `tests/integration/` | New | TDD unit + moto-S3 integration tests |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Otter API shape drifts from ReDoc samples (noted in docs: "non-breaking changes added without communication") | Med | Fixtures tagged with `source: redoc-sample`; CI never calls live API; update fixtures on API version bump. |
| Public API base URL varies per merchant — misconfiguration tanks ingestion silently | Low | `merchant_credentials.public_api_url` validated at onboarding; CLI errors loudly if blank. |
| S3 KMS permissions in dev | Med | `moto[s3]` for tests; no real AWS calls in CI. |
| 400-line budget creep on report dual-write logic | Med | Cap fixture files at 4; report manifest kept minimal (POST body echo). |

## Rollback Plan

Revert PR branch (additive; no downstream readers yet). `aws s3 rm s3://ofae-data-lakehouse-bronze-{env}/otter/merchant_id=<id>/ --recursive`. `uv remove` for added deps. No DB migrations to revert (only stub `pipeline_execution_logs` inserts).

## Dependencies

Runtime: `requests` 2.32.4, `boto3` 1.42.18, `cryptography` 42.0.5, `psycopg2-binary`, `click` 8.x. Test: `pytest` 9.0.3, `responses` 0.25.x, `moto[s3]` 5.x, `freezegun` 1.5.x, `ruff`, `mypy`, `black`. Env: `OMCAE_PG_DSN` (no schema in PR1), standard boto3 creds chain. Docs: Otter Public API reference at developer-guides.tryotter.com; rate-limiting guide at /docs/guides-rate-limiting/.

## Success Criteria

- [ ] `uv sync` + `pytest` green with ≥ 80% coverage on `src/omc_analytics/ingestion/`.
- [ ] CLI run against moto-mocked S3 writes one JSON object per endpoint to the correct Hive key.
- [ ] Reports path writes BOTH enqueue manifest AND final job result as separate S3 objects.
- [ ] 429 → 3 backoff retries → raise test present and green.
- [ ] 401 → single retry → 401 again → refresh → retry succeeds test present and green.
- [ ] No real AWS/Otter/Postgres network call during `pytest`.
- [ ] PR diff < 400 changed lines (forecast ≈ 390).
- [ ] sdd-spec produces `specs/bronze-ingestion/spec.md` + `specs/local-test-mocking/spec.md` next.

## Estimated Changed Lines

| File | Approx. LOC |
|------|-------------|
| `pyproject.toml` | 30 |
| `src/omc_analytics/__init__.py` | 2 |
| `src/omc_analytics/common/{config,logging,secrets}.py` | 28 |
| `src/omc_analytics/ingestion/__init__.py` | 1 |
| `src/omc_analytics/ingestion/otter_client.py` | 40 |
| `src/omc_analytics/ingestion/oauth.py` | 28 |
| `src/omc_analytics/ingestion/backoff.py` | 12 |
| `src/omc_analytics/ingestion/bronze_writer.py` | 35 |
| `src/omc_analytics/ingestion/run.py` | 30 |
| `tests/conftest.py` | 12 |
| `tests/unit/ingestion/test_otter_client.py` | 35 |
| `tests/unit/ingestion/test_oauth.py` | 30 |
| `tests/unit/ingestion/test_backoff.py` | 18 |
| `tests/unit/ingestion/test_bronze_writer.py` | 28 |
| `tests/unit/ingestion/test_run.py` | 25 |
| `tests/integration/test_bronze_s3.py` | 22 |
| `tests/fixtures/otter/orders_sample.json` | 12 |
| `tests/fixtures/otter/reports_enqueue_sample.json` | 3 |
| `tests/fixtures/otter/reports_result_sample.json` | 12 |
| `tests/fixtures/otter/oauth_token_sample.json` | 3 |
| `__init__` files (tests/) | 2 |
| **Total forecast** | **≈ 390** |

Review-budget risk: **low** — under 400-line cap; report dual-write adds ~7 lines to `bronze_writer.py` vs single-write path.
