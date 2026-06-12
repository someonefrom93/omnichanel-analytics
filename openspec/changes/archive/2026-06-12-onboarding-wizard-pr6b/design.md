# Design: Error Banners + Onboarding Wizard (PR6b)

## Technical Approach

Two independent serving-layer modules, zero new dependencies:
1. `error_banners.py`: pure `classify()` + 3 render helpers. Import-only — called by any page catching exceptions.
2. `pages/onboarding.py`: 4-step Streamlit wizard with `st.session_state.step` state machine.
3. `streamlit_app.py`: register onboarding page in `st.navigation`.

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| classify() shape | Pure function `(exc) -> str`, no class | No state; defensive `except Exception` fallback. Testable without mocks |
| Render helpers signature | `render_tier1_warning(exc)`, `render_tier2_info(exc)`, `render_tier3_generic(exc, alerts)` | Tier 3 needs AlertsPort; Tier 1/2 are pure rendering |
| Wizard state variable | `st.session_state.step` (int, 0-3) | Simpler than `onboarding_step`; convention from sub-brief |
| Step transitions | Button clicks set `st.session_state.step = N` + `st.rerun()` | Streamlit native pattern; no custom routing |
| OAuth callback detection | `st.query_params.get("code")` in step 1 | Streamlit 1.32+ stable API |
| Sync execution | `run_bronze_impl(ctx)` in-process (no subprocess) | Simple; logs captured via InMemoryLogs |
| Authorize URL builder | `os.environ` + f-string | Configurable via `OMCAE_OTTER_AUTHORIZE_URL`; MVP placeholder |
| streamlit_app.py change | Add `st.Page("pages/onboarding.py", ...)` to nav list | Mirrors existing cogs/dashboard pattern |

## Data Flow

```
User → Step 0 (Connect)
         │ button click → Otter authorize URL
         ▼
Otter callback → Step 1 (Callback)
         │ exchange_authorization_code → SecretsPort.save
         ▼
Step 2 (Sync)
         │ run_bronze_impl(ctx) → LogsPort rows
         ▼
Step 3 (Success)
         │ green check + dashboard link
         ▼
Done
```

Error path: any exception → `classify(exc)` → render correct tier banner.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/omc_analytics/serving/error_banners.py` | Create | `classify()`, 3 render helpers, message constants |
| `src/omc_analytics/serving/pages/onboarding.py` | Create | 4-step wizard with state machine |
| `src/omc_analytics/serving/streamlit_app.py` | Modify | +onboarding `st.Page` in navigation |
| `tests/unit/serving/test_error_banners.py` | Create | Unit tests: classify 5 cases, 3 renderer cases |
| `tests/unit/serving/test_onboarding.py` | Create | AppTest: 4 step scenarios |

## Interfaces / Contracts

```python
# error_banners.py
def classify(exc: Exception) -> str: ...
def render_tier1_warning(exc: Exception) -> None: ...
def render_tier2_info(exc: Exception) -> None: ...
def render_tier3_generic(exc: Exception, alerts) -> None: ...
```

```python
# pages/onboarding.py — 4 render helpers + dispatcher
def render_step_connect() -> None: ...
def render_step_callback(secrets, oauth) -> None: ...
def render_step_sync(ctx) -> None: ...
def render_step_success() -> None: ...
```

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | `classify()` 5 cases (Tier1AuthError, Tier2LatencyError, ValueError, KeyError, bare Exception) | Pure function; no mocks |
| Unit | `render_tier1_warning`, `render_tier2_info` | AppTest; assert `st.warning`/`st.info` rendered |
| Unit | `render_tier3_generic` | AppTest + InMemoryAlerts; assert `st.error` + alert inserted |
| Unit | Wizard step 0 renders | AppTest; assert connect UI present |
| Unit | Step 1 callback with `st.query_params["code"]` | AppTest query_params injection |
| Unit | Step 3 success UI | AppTest; assert `st.success` + link |
| Unit | App entry registers onboarding page | AppTest; assert page navigable |

## Migration / Rollout

No migration. All files are additive. Registration in `streamlit_app.py` adds one `st.Page` entry.
Rollback: revert the merge commit — removes the page from nav and restores previous state.

## Open Questions

- [ ] None. All decisions locked per umbrella proposal and sub-brief.
