# Exploration: onboarding-pr6 (Onboarding Wizard + Tier 1/2/3 Errors + OAuth authorization_code)

> Change key: `onboarding-pr6`. Final production PR — Streamlit wizard, OAuth authorization_code
> flow against Otter, three-tier error mapping, engineering_alerts table.
> Modes: `hybrid` (OpenSpec files + Engram persistence).

## Current State

- **OAuth today** (`ingestion/oauth.py::OAuthRefresher`): only `grant_type=client_credentials`.
  PR1 archived design explicitly notes: "OAuth wizard PR" was deferred. The
  OtterClient's `_request_with_401_recovery` calls `oauth.ensure_fresh_token`
  → `creds.refresh_token` → `POST /v1/auth/token` with `grant_type=refresh_token`.
- **Secrets today** (`common/secrets.py` + `common/kms_secrets.py`): `KMSSecrets`
  envelope-encrypts `MerchantCredentials` and persists to a `BlobStore`. PR2a
  ships `InMemoryBlobStore`; production `PostgresBlobStore` is **still a
  follow-up** but `MerchantCredentials.model_dump_json()` round-trips cleanly
  with the new `client_id` / `public_api_url` / `access_token` / `refresh_token`
  fields that the wizard must populate.
- **LogsPort today** (`common/logs.py` + `common/postgres_logs.py`): two-method
  Protocol — `insert_started(RunLog) -> UUID` and `update_finished(run_id, ...)`.
  Backed by `PostgresLogs` (psycopg2 `ThreadedConnectionPool` + injected
  `connection_factory`). DDL `001_create_pipeline_execution_logs.sql` uses
  CHECK (status IN ('STARTED','SUCCESS','FAILED')) — fits a 3-status workflow,
  not the 4-field alert row we need.
- **Serving today** (`serving/streamlit_app.py` + `serving/pages/{cogs_editor,dashboard}.py`):
  sidebar `st.text_input` for `merchant_id`. No OAuth. No wizard. No banners.
  Native Streamlit widgets + `AppTest` for testing.
- **PR1 Otter API research** (per `scaffold-bronze-ingestion/design.md` and
  proposal §Locked): `POST /v1/auth/token` accepts `grant_type=client_credentials`
  / `refresh_token` / **`authorization_code`** with form body `{grant_type,
  client_id, client_secret, refresh_token | code, redirect_uri}`. Returns
  `{access_token, refresh_token?, expires_in, scope, token_type}`. Otter's
  authorize URL is on the standard OAuth2 `https://api.otter.dev/oauth/authorize`
  shape (per PR1's discovery; exact path TBD by `OMCAE_OTTER_AUTHORIZE_URL` env
  var so we don't hard-code vendor secrets).
- **DDL pattern** (`001_create_pipeline_execution_logs.sql`): `IF NOT EXISTS`,
  named PK, named indexes, snake_case columns, `TIMESTAMPTZ` for time. The
  new `engineering_alerts` table MUST follow the same shape.
- **Config layer** (`common/config.py`): `secrets_factory` and `logs_factory`
  resolve from `OMCAE_*` env vars. PR6 will add **one** new env: the Otter
  authorize URL (no new backend — reuses existing factories).

## Affected Areas

- `src/omc_analytics/serving/streamlit_app.py` — register the new onboarding
  page in `st.navigation`; switch the sidebar from `text_input` to a
  read-only "Connection status" micro-indicator (per PRD §6.4) backed by
  `secrets.load(merchant_id)` lookup.
- `src/omc_analytics/serving/pages/onboarding.py` — **NEW**: 4-step wizard
  (connect → callback → initial Bronze sync → success). Reads
  `st.query_params` for the OAuth callback (`code`, `state`).
- `src/omc_analytics/serving/error_banners.py` — **NEW**: pure mapping
  function `classify(exc) -> Tier` and three `st.warning` / `st.info`
  / hidden-render functions. Mirrors PR1's "pure orchestration / I/O shell"
  split.
- `src/omc_analytics/serving/otter_callback.py` — **NEW**: pure handler
  that validates `state`, calls `oauth.exchange_authorization_code(...)`,
  and persists via `secrets.save(...)`. Pure → easy to unit-test without
  Streamlit.
- `src/omc_analytics/ingestion/oauth.py` — **MODIFY**: add
  `exchange_authorization_code(*, client_id, client_secret, code,
  redirect_uri) -> MerchantCredentials` (mirrors `request_initial_token`'s
  structure but for the `authorization_code` grant). The PR1 function stays
  for backfill / non-wizard bootstraps.
- `src/omc_analytics/common/migrations/003_create_engineering_alerts.sql` —
  **NEW**: 6-col table (id, severity, error_class, error_message, stack_trace,
  created_at) with `CHECK (severity IN ('warning','error','critical'))`.
- `src/omc_analytics/common/logs.py` + `common/postgres_logs.py` +
  `common/sqlite_logs.py` + `common/config.py` — **MODIFY**: add
  `EngineeringAlertsPort` Protocol + `InMemoryEngineeringAlerts` stub +
  `PostgresEngineeringAlerts` impl. The factory pattern matches
  `LogsPort` exactly. NOTE: requires a second table — defer the
  `PostgresEngineeringAlerts` SQL table aliasing to a future PR if we want
  to keep this PR small (see Fork 4).
- `src/omc_analytics/ingestion/run.py` — **MODIFY**: in the `except
  Exception` block, classify the exception via the Tier mapper and call
  `alerts.insert(...)` for Tier 3 only. Tier 1/2 raise normally (the
  Streamlit page catches them).
- `src/omc_analytics/ingestion/errors.py` — **MODIFY**: add
  `Tier1AuthError`, `Tier2LatencyError`, `Tier3InternalError` thin wrappers
  so the Streamlit page can `except Tier1AuthError` without coupling to
  `KMSSecrets.OAuthRefreshError` (which lives in a different module).
- `tests/unit/ingestion/test_oauth.py` — **MODIFY**: add
  `test_exchange_authorization_code` (3 cases: happy path, non-200,
  missing code param).
- `tests/unit/serving/test_error_banners.py` — **NEW**: pure unit tests
  for `classify(exc) -> Tier` across 401/403/502/503/unexpected/empty.
- `tests/unit/serving/test_onboarding.py` — **NEW**: AppTest scenarios
  for all 4 steps, including the `st.query_params["code"]` callback path.
- `tests/integration/test_onboarding_e2e.py` — **NEW**: full happy path
  using `responses` to mock Otter's authorize/token endpoints + moto S3
  for the Bronze write.
- `pyproject.toml` — confirm `streamlit>=1.32,<2.0` (already in from PR5);
  no new runtime deps.
- `.env.example` — add `OMCAE_OTTER_AUTHORIZE_URL`,
  `OMCAE_OTTER_TOKEN_URL`, `OMCAE_OAUTH_REDIRECT_URI`.

## Approaches

### Fork 1 — OAuth `authorization_code` flow shape

| Option | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A. Server-side redirect via Streamlit** (chosen) | `st.button("Connect")` → `st.markdown(f"[Click here]({authorize_url})")` with `client_id`, `redirect_uri`, `state`, `scope=read+reports` query params. User authorizes on Otter's site, returns to `?code=...&state=...`. Page reads `st.query_params` in the same render. | Standard pattern; works without a custom backend; AppTest can inject `query_params={"code": "abc"}` to simulate the callback. | `state` is enforced client-side (Streamlit has no real "session" for state cookies in a single-page flow) — mitigated by storing `state` in `st.session_state` before the redirect. | Low |
| **B. `st.experimental_set_query_params` to drive a flow inside the app** | Stay inside Streamlit; mimic the redirect with internal state | No real Otter round-trip needed in tests | Doesn't actually demonstrate the OAuth dance; spec demands the real authorize URL; defeats the spec's purpose | Med (and **wrong**) |
| **C. Custom FastAPI/Flask wrapper** | Stand up a tiny HTTP service to handle the callback | Proper `state` cookie + CSRF | Violates "no new infra" hard constraint; PRD pins Streamlit | Med-High (rejected by constraint) |

**Recommendation: A.** Mirror the PR1 `request_initial_token` shape
(form-encoded POST to `/v1/auth/token` with `grant_type=authorization_code`).
Add `state` to `st.session_state` BEFORE the redirect, then validate on
callback. The `state` is the only real CSRF protection in this single-app
context — it's enough for a dev/MVP surface area.

### Fork 2 — Where to persist the engineering alert

| Option | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A. New `engineering_alerts` PostgreSQL table** (chosen) | 6-col table, DDL `003_create_engineering_alerts.sql`, `EngineeringAlertsPort` Protocol + InMemory + Postgres impls | Mirrors `pipeline_execution_logs` pattern exactly; dedicated schema; queryable for dashboards | Adds a second DDL migration; PR6 must run it | Low |
| **B. Reuse `pipeline_execution_logs` with a new `pipeline_name = 'engineering_alert'`** | No new table; piggyback on existing LogsPort | One table; no DDL | Schema is wrong (no `severity`, no `stack_trace`); the CHECK constraint on `status` doesn't apply | Low impl, **Med debt** |
| **C. Send straight to Sentry / PagerDuty SDKs in-process** | Skip persistence, alert directly | No table; prod-ready alerting | Hard constraint says **out of scope**: "defer the actual production wiring (PagerDuty/Sentry) — just the table + LogsPort impl" | Low impl, **rejected by constraint** |

**Recommendation: A.** New `engineering_alerts` table, new Port, new
impls. The pattern is identical to `LogsPort` — copy it.

### Fork 3 — Tier 1/2/3 classification: where it lives

| Option | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A. In `serving/error_banners.py` as a pure function** (chosen) | `classify(exc) -> Literal["tier1","tier2","tier3"]` lives in the serving layer; the ingestion layer wraps exceptions into typed `Tier1AuthError` / `Tier2LatencyError` / re-raises as Tier 3. | Pure → easy to unit test; serving decides UX; ingestion stays free of UI knowledge. | Two-file contract (errors.py + error_banners.py) | Low |
| **B. In `ingestion/errors.py` itself** | Each exception has a `tier` attribute | Single source of truth; the Layer 3 "if anything else → Tier 3" becomes a fallback in the mapper | Tighter coupling: ingestion knows about UX tiers; can't unit-test the classifier without importing Streamlit | Med |
| **C. In the Streamlit page itself** | `if isinstance(exc, OAuthRefreshError): st.warning(...)` | Locality | Duplicated across every page; not testable as a unit | Low impl, **High debt** |

**Recommendation: A.** The mapper is a pure function. The ingestion
layer raises typed exceptions; the serving layer renders them. PRD §5.2
is a UI spec, not an ingestion spec — keep the boundary clean.

### Fork 4 — Wizard step persistence: full page rerun vs `st.session_state` machine

| Option | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A. Single page, `st.session_state.step` integer + `st.rerun()`** (chosen) | One file, one `st.session_state["onboarding_step"]`; each step renders conditionally | AppTest-friendly (no page-switching); state lives in session; one file to test | `st.rerun()` is necessary; AppTest must seed `session_state` per test | Low |
| **B. 4 separate pages + `st.switch_page`** | One page per step | Native Streamlit feel | AppTest per page; state must pass via `st.session_state` anyway; more files | Med |
| **C. Single page, no `st.rerun()` — use `st.form` to commit each step** | Multi-step form | No rerun | Forms aren't designed for branching next-steps; less idiomatic | Low impl, **bad UX** |

**Recommendation: A.** The simplest approach that fits Streamlit 1.32's
single-page rerun model. The state machine is just an int in
`st.session_state`. Each `if step == N:` block renders. AppTest seeds
`session_state` directly.

### Fork 5 — PR split strategy (Review Workload Guard)

Forecast for PR6 in a single PR: ~700-900 LOC across ~12 files
(migration + Port + Postgres impl + 3 typed errors + 2 serving modules
+ wizard + banners + ~5 test files + README updates). This is
**above the 400-line review budget by ~2x**.

| Option | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A. Single PR** (PR6 itself) | Everything in one go | No coordination overhead; one verification cycle; the user said "toma las mejores decisiones" | Reviewer cognitive load exceeds the 400-line guard; harder to review error-mapping logic AND OAuth flow AND wizard UX in one sitting | High review cost |
| **B. Two chained PRs: PR6a (OAuth + error mapping + table) then PR6b (wizard UI)** | PR6a is the data plumbing + persistence (~500 LOC). PR6b is the Streamlit wizard + banner rendering (~300 LOC). | Each slice < 400 LOC; PR6a can be verified by integration tests; PR6b is pure UI; rollback is cleaner | Two PRs to manage; user said "single PR6"; if we split, we should be explicit | Med |
| **C. Single PR with all 700 LOC, no split** | As written | Simpler to track | Violates the Review Workload Guard | High review cost |

**Recommendation: B (two chained PRs), but call it a single umbrella
`onboarding-pr6` with two child slices.** The user said "may need a
small split — but the user said 'toma las mejores decisiones', so decide
and surface in the proposal." The data plumbing (OAuth + alerts table +
typed errors + mapper) is independently shippable and verifiable. The
wizard is the last UI layer. Splitting protects reviewers and lets the
second slice get fast iteration on UX without blocking on the OAuth
plumbing review.

## Recommendation

Proceed as **PR6 umbrella = `onboarding-pr6`**, sliced into:

- **PR6a — OAuth + error mapping + alerts table** (~500 LOC, ~7 files)
- **PR6b — Onboarding wizard + banner rendering** (~300 LOC, ~5 files)

PR6a is the safety-critical backend: it adds the typed errors, the
`authorization_code` grant, the `EngineeringAlertsPort` + Postgres impl,
and the pure `classify(exc) -> Tier` mapper. PR6b is pure UI on top.

The alternative is a single 700-900 LOC PR. The Review Workload Guard
exists for a reason — and the orchestrator brief explicitly
acknowledges the budget risk by surfacing the decision in the proposal.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Otter's authorize URL is unknown without an Otter dev account | Med | Make it env-configurable (`OMCAE_OTTER_AUTHORIZE_URL`); default to a documented placeholder; spec calls out the env var |
| `st.query_params` returns a dict-like whose reads differ across Streamlit 1.32 vs 1.40 | Low | Use the stable API `st.query_params.get("code")`; AppTest injection is supported in 1.32 |
| `state` CSRF is enforced via `st.session_state` — but session_state is reset on browser close | Med | Document the limitation; PR6 is a dev/MVP surface; harden in a future PR with proper server-side state |
| `MerchantCredentials.refresh_token` is `str | None` — wizard flow must always set it | Low | Pydantic model already enforces non-None when we `model_copy(update=...)`; unit test asserts `refresh_token is not None` after exchange |
| `EngineeringAlertsPort` doubles the LogsPort surface area — drift risk | Med | Single factory in `common/config.py`; same `OMCAE_LOGS_BACKEND` env var picks both |
| `classify()` must handle exceptions that are NOT in `ingestion.errors` (e.g. `KeyError` from JSON parsing) | Med | Defensive `except Exception: return "tier3"` fallback; explicit unit tests for `ValueError`, `KeyError`, `JSONDecodeError` |
| The `if step == N:` pattern in onboarding.py is hard to test in isolation | Low | Each step is a `def render_step_N(state, secrets, ...)` helper; the top-level page is a 4-line dispatcher |
| Splitting into PR6a/PR6b doubles the merge coordination | Low | Both slices target the same `feature/onboarding-pr6` branch; PR6b's `git diff` against `main` will show the whole change set — but we rebase/retarget per the chained-PRs convention in `sdd-phase-common.md` §E |

## Ready for Proposal

**Yes.** All five design forks resolved. The two-sliced split
recommendation is the most important decision to surface in the
proposal — it changes the user-facing deliverable from "one PR" to "an
umbrella with two child slices" but each slice stays under the 400-line
review budget. The OAuth flow mirrors PR1's `request_initial_token` for
predictability. The Tier 1/2/3 mapping is a pure function in the serving
layer. The `engineering_alerts` table is a near-clone of the
`pipeline_execution_logs` DDL pattern.

The new capabilities to spec are:
- `onboarding-wizard` — the 4-step Streamlit wizard
- `tier-error-mapping` — Tier 1/2/3 classification + banner rendering
- `oauth-authorization-code` — Otter's `authorization_code` grant
- `engineering-alerts` — the new `engineering_alerts` table + Port
