# Tasks: Error Banners + Onboarding Wizard (PR6b)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~300 LOC |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Phase 1: Error Banners

- [ ] 1.1 Create `src/omc_analytics/serving/error_banners.py` with `classify(exc)`, 3 render helpers, message constants
- [ ] 1.2 Write `tests/unit/serving/test_error_banners.py`: classify 5 cases, 3 renderer cases (AppTest)
- [ ] 1.3 Run `uv run pytest tests/unit/serving/test_error_banners.py -x` — all GREEN

## Phase 2: Onboarding Wizard

- [ ] 2.1 Create `src/omc_analytics/serving/pages/onboarding.py` with 4-step wizard (state machine + render helpers)
- [ ] 2.2 Update `src/omc_analytics/serving/streamlit_app.py` — register onboarding page in `st.navigation`
- [ ] 2.3 Write `tests/unit/serving/test_onboarding.py`: AppTest for all 4 steps
- [ ] 2.4 Run `uv run pytest tests/unit/serving/test_onboarding.py -x` — all GREEN

## Phase 3: Quality Gates

- [ ] 3.1 `uv run ruff check` — clean
- [ ] 3.2 `uv run mypy src/omc_analytics` — clean
- [ ] 3.3 Full test suite: `uv run pytest -x` — all GREEN
- [ ] 3.4 Git commit with conventional message
