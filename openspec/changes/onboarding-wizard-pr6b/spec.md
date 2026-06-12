# Spec: Error Banners + Onboarding Wizard (PR6b)

> Delta spec. Change: `onboarding-wizard-pr6b`. All sections are ADDED (no existing specs).

## ADDED Requirements — Error Banners

### Requirement: classify exception to Tier

`classify(exc: Exception) -> Literal["tier1", "tier2", "tier3"]` SHALL be a pure function:
- `Tier1AuthError` → `"tier1"`
- `Tier2LatencyError` → `"tier2"`
- Any other `Exception` → `"tier3"` (defensive fallback).

#### Scenario: Tier1AuthError maps to tier1
- GIVEN a `Tier1AuthError` instance
- WHEN `classify(exc)` is called
- THEN returns `"tier1"`

#### Scenario: Tier2LatencyError maps to tier2
- GIVEN a `Tier2LatencyError` instance
- WHEN `classify(exc)` is called
- THEN returns `"tier2"`

#### Scenario: Unknown Exception maps to tier3
- GIVEN a plain `ValueError("boom")`
- WHEN `classify(exc)` is called
- THEN returns `"tier3"` via defensive `except Exception` fallback

### Requirement: Tier 1 renderer displays warning

`render_tier1_warning(exc: Exception) -> None` SHALL call `st.warning(TIER1_MESSAGE)`.

#### Scenario: Warning banner for auth failure
- GIVEN a `Tier1AuthError`
- WHEN `render_tier1_warning(exc)` is called
- THEN `st.warning` is rendered with user-actionable message

### Requirement: Tier 2 renderer displays info

`render_tier2_info(exc: Exception) -> None` SHALL call `st.info(TIER2_MESSAGE)`.

#### Scenario: Info banner for latency
- GIVEN a `Tier2LatencyError`
- WHEN `render_tier2_info(exc)` is called
- THEN `st.info` is rendered with latency message

### Requirement: Tier 3 renderer displays generic error + alerts

`render_tier3_generic(exc: Exception, alerts: AlertsPort) -> None` SHALL call `st.error(TIER3_MESSAGE)` AND write an `EngineeringAlert` via `alerts.insert_alert(...)`.

#### Scenario: Generic error with alert write
- GIVEN a plain `Exception` and an `InMemoryAlerts` instance
- WHEN `render_tier3_generic(exc, alerts)` is called
- THEN `st.error` is rendered AND one alert is inserted into `alerts`

## ADDED Requirements — Onboarding Wizard

### Requirement: 4-step state machine

The wizard SHALL use `st.session_state.step` (int, default 0) to render one of four steps.
Step transitions SHALL be triggered by buttons and validated conditions, followed by `st.rerun()`.

#### Scenario: Fresh session starts at step 0
- GIVEN no `step` in `st.session_state`
- WHEN the onboarding page loads
- THEN step 0 (Connect) is rendered

### Requirement: Step 0 — Connect

`render_step_connect()` SHALL display a button or link to Otter's authorize URL with
`client_id`, `redirect_uri`, `state`, `scope=read+reports` query parameters.

#### Scenario: Connect button opens authorize URL
- GIVEN step 0 is rendered
- WHEN the page loads
- THEN a Connect button or markdown link with Otter authorize URL is displayed

### Requirement: Step 1 — Callback

`render_step_callback()` SHALL read `?code=...` from `st.query_params`, call
`OAuthRefresher.exchange_authorization_code(code, redirect_uri)`, persist returned
`MerchantCredentials` via `SecretsPort.save`, and advance to step 2.

#### Scenario: Valid code exchanges and persists
- GIVEN `st.query_params` contains `code=abc123`
- WHEN step 1 renders
- THEN `exchange_authorization_code` is called, creds are persisted, step advances to 2

### Requirement: Step 2 — Sync

`render_step_sync()` SHALL call `run_bronze_impl(ctx)` in-process and display
LogsPort rows as they appear via `st.write`.

#### Scenario: Sync runs and shows logs
- GIVEN step 2 is active and dependencies are wired
- WHEN the sync step renders
- THEN `run_bronze_impl(ctx)` is called and log rows are displayed

### Requirement: Step 3 — Success

`render_step_success()` SHALL display a green checkmark and a link to the dashboard page.

#### Scenario: Success shows green check and dashboard link
- GIVEN step 3 is active
- WHEN the success step renders
- THEN page displays `st.success` and a dashboard link
