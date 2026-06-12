# Proposal: Onboarding Wizard + Tier 1/2/3 Error Mapping + OAuth authorization_code (PR6)

## Intent

Ship the **last production PR** of OFAE. Three deliverables from PRD §5.2
and §6.4:

1. A Streamlit **onboarding wizard** that walks a merchant from "no Otter
   connection" → "first Bronze sync complete" in <60 seconds, matching the
   §1.3 success metric.
2. The **Tier 1/2/3 error mapping** that turns raw `OAuthRefreshError` /
   5xx / internal exceptions into the three PRD §5.2 user-facing messages
   (warning / info / hidden).
3. The **Otter `authorization_code` OAuth flow** (per PR1's research and
   `scaffold-bronze-ingestion/proposal.md` "deferred to OAuth wizard PR"),
   storing tokens in `merchant_credentials` envelope-encrypted via
   `KMSSecrets`.

The change is the only place where §5.2's mapping, §6.4's wizard, and
§2.3's refresh loop converge. It also adds the `engineering_alerts` table
that catches Tier 3 errors for future PagerDuty/Sentry wiring (out of
scope here — only the table + LogsPort impl).

## Scope

### In Scope

- **OAuth `authorization_code` grant** in `ingestion/oauth.py`
  (`exchange_authorization_code(...)`) mirroring `request_initial_token`'s
  shape — form-encoded `POST /v1/auth/token` with `grant_type=authorization_code`,
  `code`, `redirect_uri`, `client_id`, `client_secret`. Returns
  `MerchantCredentials` with `access_token` + `refresh_token` + `expires_at`.
- **Onboarding wizard page** at
  `src/omc_analytics/serving/pages/onboarding.py` — 4 steps driven by
  `st.session_state["onboarding_step"]`:
  1. "Connect your Otter account" — `st.button` → redirect to Otter's
     authorize URL with `client_id`, `redirect_uri`, `state`, `scope=read+reports`.
  2. OAuth callback — read `st.query_params` for `code` + `state`, validate
     `state` against `st.session_state["oauth_state"]`, exchange code, save
     to `merchant_credentials` via `KMSSecrets`.
  3. "Initial Bronze sync" — call `run_bronze_impl` in-process via
     `_build_deps` (no CLI) and stream `LogsPort` rows as they appear.
  4. "Success" — green check + link to dashboard.
- **Tier 1/2/3 mapping** in `serving/error_banners.py` (pure function
  `classify(exc) -> Literal["tier1","tier2","tier3"]`) + three render
  helpers (`render_tier1`, `render_tier2`, `render_tier3`). Tier 3 hidden
  from the user; the alert is routed to `EngineeringAlertsPort.insert(...)`.
- **Typed errors** in `ingestion/errors.py`: `Tier1AuthError`,
  `Tier2LatencyError` — thin wrappers raised by the ingestion layer
  before the exception reaches the Streamlit page. `Tier3InternalError`
  is a `pass` marker (no class needed — `Exception` is Tier 3 by default).
- **`engineering_alerts` table** DDL
  `common/migrations/003_create_engineering_alerts.sql` (6 columns,
  `IF NOT EXISTS`, named index on `(created_at DESC)`).
- **`EngineeringAlertsPort` Protocol** + `InMemoryEngineeringAlerts` +
  `PostgresEngineeringAlerts` in `common/alerts.py` (mirrors
  `LogsPort` exactly).
- **Streamlit app entry** modification: remove the sidebar `text_input`
  merchant_id (replaced by a read-only "Connection status" micro-indicator
  per PRD §6.4); add the onboarding page to `st.navigation`.
- **Unit tests** for: `exchange_authorization_code` (3 cases), `classify`
  (6 cases across 401/403/502/503/unexpected/empty), banner rendering
  (3 cases), wizard steps via `AppTest` (4 cases), engineering_alerts
  round-trip (2 cases). **All 3 error tiers MUST be unit-tested.**
- **Integration test** for the full happy path: `responses` mocks Otter's
  authorize + token endpoints, moto S3 hosts Bronze, the wizard runs
  end-to-end in `AppTest`.

### Out of Scope

- **Webhooks**, **cron / EventBridge scheduling**, **real Sentry / PagerDuty
  wiring** — explicit hard constraints.
- **Real Otter production app registration** — Otter's authorize URL is
  env-configurable; PR6 ships with a documented placeholder
  (`https://api.otter.dev/oauth/authorize`).
- **Multi-merchant per user** — one Streamlit session = one merchant_id.
- **HTTPS / CSRF cookie hardening** — `state` is enforced via
  `st.session_state` only (documented limitation).
- **App Runner deployment** — dev/local-only; deployment script deferred.

## Capabilities

> Contract with sdd-spec. Two new capabilities; one modified.

### New Capabilities
- `onboarding-wizard`: the Streamlit 4-step wizard page (connect → callback
  → initial sync → success) driven by `st.session_state["onboarding_step"]`.
- `tier-error-mapping`: the pure `classify(exc) -> Tier` mapper + three
  banner render helpers (`render_tier1`, `render_tier2`, `render_tier3`)
  + the typed exceptions (`Tier1AuthError`, `Tier2LatencyError`).
- `oauth-authorization-code`: the `exchange_authorization_code` method
  on `OAuthRefresher` — Otter's `grant_type=authorization_code` flow.
- `engineering-alerts`: the `EngineeringAlertsPort` Protocol +
  InMemory + Postgres impls + the `engineering_alerts` DDL migration.

### Modified Capabilities
- `bronze-ingestion`: the `run_bronze_impl` `except` block now classifies
  the exception and calls `alerts.insert(...)` for Tier 3 — Tier 1/2
  exceptions are re-raised as typed `Tier1AuthError` / `Tier2LatencyError`.
- `streamlit-serving`: the sidebar `text_input` becomes a read-only
  connection-status micro-indicator; the navigation gains the
  `Onboarding` page.

## Approach

The work is a **single umbrella `onboarding-pr6` with two chained child
PR slices**, recommended to protect the 400-line review budget
(`sdd-phase-common.md` §E):

- **PR6a (scaffold + plumbing, ~500 LOC, ~7 files)**
  - `ingestion/oauth.py` — add `exchange_authorization_code`
  - `ingestion/errors.py` — add `Tier1AuthError`, `Tier2LatencyError`
  - `ingestion/run.py` — wrap re-raise in typed errors; insert Tier 3
    into `EngineeringAlertsPort`
  - `common/alerts.py` — NEW: `EngineeringAlertsPort` + InMemory + Postgres
  - `common/migrations/003_create_engineering_alerts.sql` — NEW
  - `common/config.py` — add `alerts_factory` (mirrors `logs_factory`)
  - `serving/error_banners.py` — NEW: pure `classify(exc) -> Tier`
  - ~5 test files

- **PR6b (UI, ~300 LOC, ~5 files)**
  - `serving/pages/onboarding.py` — NEW: 4-step wizard
  - `serving/streamlit_app.py` — register the new page; replace
    sidebar `text_input` with connection-status micro-indicator
  - `serving/error_banners.py` — add the three `render_tierN` helpers
  - `tests/unit/serving/test_onboarding.py` — NEW: AppTest scenarios
  - `tests/integration/test_onboarding_e2e.py` — NEW: full happy path

**Why split?** The 700-900 LOC forecast for a single PR is **2x the
400-line review budget** set by `sdd-phase-common.md` §E. PR6a is
data plumbing + persistence (independently verifiable via the typed
errors + alerts table). PR6b is the wizard UI on top. Each slice ships,
verifies, and rolls back autonomously. Both target the same
`feature/onboarding-pr6` umbrella branch; the chained-PRs convention
in §E governs retargeting.

**Alternatives rejected:**
- **Single PR**: review cognitive load exceeds budget; harder to
  isolate OAuth flow bugs from wizard UX bugs.
- **Defer the split decision to the user**: the orchestrator brief
  explicitly says "decide and surface in the proposal" — so we
  surface the split here.

**Otter's `authorization_code` shape** (per PR1's research): the
authorize URL is `https://api.otter.dev/oauth/authorize` (env-overridable
via `OMCAE_OTTER_AUTHORIZE_URL`); the token URL is
`https://api.otter.dev/v1/auth/token`; the callback query string is
`?code=<one-time>&state=<csrf>`. The exchange is a form-encoded POST
with `grant_type=authorization_code`, `code`, `redirect_uri`,
`client_id`, `client_secret`. Returns
`{access_token, refresh_token, expires_in, scope, token_type}`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/omc_analytics/ingestion/oauth.py` | Modified | +`exchange_authorization_code(...)` method on `OAuthRefresher` |
| `src/omc_analytics/ingestion/errors.py` | Modified | +`Tier1AuthError`, `Tier2LatencyError` |
| `src/omc_analytics/ingestion/run.py` | Modified | `except` block wraps re-raise in typed errors; inserts Tier 3 alerts |
| `src/omc_analytics/common/alerts.py` | **New** | `EngineeringAlertsPort` + InMemory + Postgres impls |
| `src/omc_analytics/common/migrations/003_create_engineering_alerts.sql` | **New** | DDL: id, severity, error_class, error_message, stack_trace, created_at |
| `src/omc_analytics/common/config.py` | Modified | +`alerts_factory` |
| `src/omc_analytics/serving/pages/onboarding.py` | **New** | 4-step wizard |
| `src/omc_analytics/serving/error_banners.py` | **New** | Pure `classify` + render helpers |
| `src/omc_analytics/serving/streamlit_app.py` | Modified | Register onboarding page; replace sidebar `text_input` with status indicator |
| `tests/unit/ingestion/test_oauth.py` | Modified | +`test_exchange_authorization_code` (3 cases) |
| `tests/unit/serving/test_error_banners.py` | **New** | `classify` unit tests (6 cases) |
| `tests/unit/serving/test_onboarding.py` | **New** | AppTest wizard scenarios (4 cases) |
| `tests/integration/test_onboarding_e2e.py` | **New** | Full happy-path e2e |
| `pyproject.toml` | No change | `streamlit>=1.32` already present from PR5 |
| `.env.example` | Modified | +`OMCAE_OTTER_AUTHORIZE_URL`, `OMCAE_OTTER_TOKEN_URL`, `OMCAE_OAUTH_REDIRECT_URI` |
| `README.md` | Modified | Document the wizard, the 3 tiers, and the alerts table |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Otter's authorize URL drifts / differs per environment | Med | Env-configurable (`OMCAE_OTTER_AUTHORIZE_URL`); default to a documented placeholder; spec calls out the env var explicitly |
| `st.query_params` API differs across Streamlit 1.32 vs 1.40 | Low | Use the stable `st.query_params.get("code")` form; AppTest injection supported in 1.32 |
| `state` CSRF enforced via `st.session_state` only — session_state resets on browser close | Med | Documented limitation; future PR can add server-side cookie; PR6 is a dev/MVP surface |
| `MerchantCredentials.refresh_token` not always set by Otter's `authorization_code` response | Med | Pydantic model accepts `Optional[str]`; unit test asserts non-None when Otter returns one; falls back to `request_initial_token` on subsequent runs if missing |
| `classify()` must handle exceptions NOT in `ingestion.errors` (KeyError, ValueError, JSONDecodeError) | Med | Defensive `except Exception: return "tier3"` fallback; explicit unit tests for the three unexpected types |
| `EngineeringAlertsPort` doubles the LogsPort surface area — drift risk | Med | Single `alerts_factory` in `common/config.py`; same `OMCAE_LOGS_BACKEND` env var picks both Ports |
| PR6a + PR6b split doubles merge coordination | Low | Both slices target the same `feature/onboarding-pr6` branch; chained-PRs convention in `sdd-phase-common.md` §E governs retargeting |
| Forecast ~700-900 LOC exceeds 400-line review budget | **High** | **Split into PR6a + PR6b** (this proposal) |
| 4-step wizard's `if step == N:` block hard to test in isolation | Low | Each step is a `def render_step_N(state, secrets, ...)` helper; the page is a 4-line dispatcher |

## Rollback Plan

- **PR6a**: revert the merge commit. The new typed errors are wrappers
  that re-raise the original; the new DDL is `CREATE TABLE IF NOT EXISTS`
  (drop with `DROP TABLE engineering_alerts`); the `alerts_factory` is
  a no-op when the Port isn't injected. **Tenant impact: zero** (no
  S3 paths or KMS keys touched).
- **PR6b**: revert the merge commit. The onboarding page is purely
  additive to `st.navigation`; reverting removes the route. The
  sidebar `text_input` removal is reversible by re-adding the input.
  **Tenant impact: zero**.
- **Umbrella**: if both slices land and a regression appears, the
  `OTTER_CLIENT_ID` / `OTTER_CLIENT_SECRET` env vars in `.env.example`
  can be unset to force the wizard to render step 1 indefinitely while
  the team debugs.

## Dependencies

- `streamlit>=1.32,<2.0` (already present from PR5).
- `requests` + `responses` (already present from PR1).
- `psycopg2` (already present from PR2a — for `PostgresEngineeringAlerts`).
- `psutil` / `freezegun` are NOT required.
- No new runtime deps.

## Success Criteria

- [ ] All 3 error tiers are unit-tested (Tier 1/2/3 each have ≥ 2 unit
      test cases).
- [ ] `classify(exc) -> Tier` returns `"tier1"` for 401/403,
      `"tier2"` for 502/503, `"tier3"` for everything else (incl.
      `KeyError`, `ValueError`, `JSONDecodeError`).
- [ ] `exchange_authorization_code(...)` round-trips a real Otter
      `authorization_code` response into a `MerchantCredentials` with
      `access_token` + `refresh_token` + `expires_at` populated, persisted
      via `KMSSecrets` (or `InMemorySecrets` in tests).
- [ ] `engineering_alerts` table is created by DDL 003; an inserted
      Tier 3 row is queryable by `severity = 'error'`.
- [ ] Streamlit wizard's 4 steps render in `AppTest`; the OAuth callback
      step reads `st.query_params["code"]`, validates `state`, and
      persists credentials.
- [ ] `omc-ingest run-bronze --merchant-id=<id> --env=dev` still works
      end-to-end (no regression in the ingestion path).
- [ ] PR6a ships under 500 LOC; PR6b ships under 350 LOC. Both pass
      ruff, mypy, black.
- [ ] `pytest --cov=src` coverage stays ≥ 80%.
- [ ] No new webhooks, cron, or Sentry/PagerDuty wiring.

## Review Workload Guard (Section E)

| Field | Value |
|---|---|
| **Estimated changed lines (total)** | ~800 LOC across ~15 files |
| **PR6a slice (plumbing)** | ~500 LOC, ~7 source files + ~5 test files |
| **PR6b slice (UI)** | ~300 LOC, ~2 source files + ~2 test files |
| **400-line budget risk** | **High** for single PR; **Low** per slice |
| **Chained PRs recommended** | **Yes** (PR6a → PR6b) |
| **Decision needed before apply** | **Yes** — confirm the 2-slice split |
| **Recommended split** | `PR6a: OAuth + errors + alerts table` → `PR6b: wizard + banners` |
| **Delivery strategy** | `auto-chain` (chained feature branch; both target `feature/onboarding-pr6`) |
