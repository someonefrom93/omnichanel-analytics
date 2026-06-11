# Tasks: Scaffold Bronze Ingestion (PR1)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ≈ 390 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Phase 1: Foundation

- [x] 1.1 **pyproject.toml** — Create `uv`-managed Python 3.12 project with deps: `requests`, `boto3`, `cryptography`, `psycopg2-binary`, `click`, `pytest`, `responses`, `moto[s3]`, `freezegun`, `ruff`, `mypy`, `black`. Files: `pyproject.toml`. *Done when: `uv sync` succeeds.*
- [x] 1.2 **Package skeleton** — Create `src/omc_analytics/__init__.py`, `common/`, `ingestion/`, `transformation/__init__.py`, `serving/__init__.py` with empty inits. Files: `src/omc_analytics/{__init__,common/__init__,ingestion/__init__,transformation/__init__,serving/__init__}.py`. *Done when: `python -c "import omc_analytics"` succeeds.*
- [x] 1.3 **conftest.py** — Stub `responses.start()`/`stop()`, `moto` S3 fixture, `freezegun` freeze decorator, fixture-load helper. Files: `tests/conftest.py`. *Done when: `pytest tests/` collects fixtures without error.*

## Phase 2: Ports & Stubs

- [ ] 2.1 **SecretsPort** — Define `SecretsPort` Protocol + `InMemorySecrets` stub in `common/secrets.py`. Files: `src/omc_analytics/common/secrets.py`. Spec refs: `specs/bronze-ingestion/spec.md` §SecretsPort. *Test-first:* `test_secrets_port_load_and_save`. *Done when: pytest passes, mypy clean.*

## Phase 3: Pure Helpers

- [ ] 3.1 **RetryPolicy** — `backoff.py`: `@dataclass RetryPolicy(max_retries, base_seconds, cap_seconds, jitter)` with `wait_for(attempt) -> float` and `should_retry(attempt) -> bool`. Files: `src/omc_analytics/ingestion/backoff.py`. Design refs: §RetryPolicy. *Test-first:* `test_retry_policy_exponential_growth`, `test_retry_policy_jitter_range`, `test_retry_policy_exhaustion`. *Done when: pytest passes ≥80% coverage on backoff.py.*
- [ ] 3.2 **build_bronze_key** — `bronze_writer.py`: pure `build_bronze_key(merchant_id, endpoint, run_timestamp_utc) -> str`. Files: `src/omc_analytics/ingestion/bronze_writer.py`. Design refs: §Path construction. *Test-first:* `test_build_bronze_key_shape`, `test_build_bronze_key_merchant_fencing`. *Done when: pytest passes, ruff clean.*

## Phase 4: Adapters

- [ ] 4.1 **BronzeWriter** — `bronze_writer.py`: `BronzeWriter.write_raw()` (boto3 `put_object`), `write_report_pair()` (dual-write for reports). Files: `src/omc_analytics/ingestion/bronze_writer.py`. Spec refs: `specs/bronze-ingestion/spec.md` §Bronze S3 Path Correctness, §Reports Async Job. Design refs: §Reports dual-write, §Bronze writer. *Test-first:* `test_bronze_writer_raw_bytes`, `test_bronze_writer_report_pair_two_keys`. *Done when: pytest passes, moto-S3 integration green.*
- [ ] 4.2 **OAuthRefresher** — `oauth.py`: `OAuthRefresher.maybe_refresh()` (10-min pre-expiry check), `force_refresh()`. Files: `src/omc_analytics/ingestion/oauth.py`. Spec refs: `specs/bronze-ingestion/spec.md` §Valid Token, §Proactive Token Refresh. Design refs: §OAuthRefresher. *Test-first:* `test_oauth_no_refresh_when_fresh`, `test_oauth_refresh_at_599s`, `test_oauth_write_back`. *Done when: pytest passes, 3 scenarios green.*
- [ ] 4.3 **OtterClient** — `otter_client.py`: `OtterClient` with `_with_401_recovery` wrapper, `fetch_orders`, `request_report`, `poll_report`, `ReportPoller`. Files: `src/omc_analytics/ingestion/otter_client.py`. Spec refs: `specs/bronze-ingestion/spec.md` §401 Two-Stage, §429 Backoff, §T-1 Window. Design refs: §OtterClient, §401 recovery, §Report polling ceiling. *Test-first:* `test_401_single_retry_success`, `test_401_double_retry_then_refresh`, `test_429_three_retries_then_success`, `test_429_fourth_exhausts`. *Done when: pytest passes, coverage ≥80% on otter_client.py.*

## Phase 5: Orchestration

- [ ] 5.1 **CLI run.py** — `ingestion/run.py`: `build_run_context()` (click CLI), `compute_t1_window()`, `LogsPort` + `InMemoryLogs`, orchestrator wiring secrets→oauth→client→writer→logs. Files: `src/omc_analytics/ingestion/run.py`, `src/omc_analytics/common/config.py`, `src/omc_analytics/common/logging.py`. Spec refs: `specs/bronze-ingestion/spec.md` §CLI Entrypoint. Design refs: §Data Flow, §RunContext, §LogsPort. *Test-first:* `test_run_success_exits_zero`, `test_run_failure_exits_nonzero`, `test_logs_insert_and_update`. *Done when: pytest passes, `python -m omc_analytics.ingestion.run --help` works.*

## Phase 6: End-to-End Integration

- [ ] 6.1 **Integration test** — `tests/integration/test_bronze_s3.py`: CliRunner or subprocess against moto + `responses`, assert S3 keys + log rows. Files: `tests/integration/test_bronze_s3.py`. Spec refs: `specs/bronze-ingestion/spec.md` §Successful run, §Bronze S3 Path. *Done when: pytest green, real network calls = 0.*
- [ ] 6.2 **Fixture files** — Create 4 JSON fixtures under `tests/fixtures/otter/` tagged `{"source": "redoc-sample", "version": "1.0"}`. Files: `tests/fixtures/otter/{orders_sample,oauth_token_sample,reports_enqueue_sample,reports_result_sample}.json`. Spec refs: `specs/local-test-mocking/spec.md` §ReDoc-Derived Fixtures. *Done when: fixtures load in tests, tagged correctly.*

## Phase 7: Polish

- [ ] 7.1 **Lint & type check** — `ruff check src/ tests/`, `mypy src/omc_analytics/`, `pytest --cov=src/omc_analytics/ingestion/ --cov-fail-under=80`. Files: all `src/`. *Done when: ruff/mypy clean, coverage ≥80% on ingestion module.*
- [ ] 7.2 **Final verification** — Confirm proposal success criteria: `uv sync` + pytest green + no real network calls + PR diff < 400 lines. Files: all. *Done when: all 7 proposal success criteria green.*
