# Tasks: pii-salted-pr4a

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~237 LOC |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Phase 1: MerchantCredentials delta + tests

- [ ] 1.1 Add `pii_salt: str | None = None` field to `MerchantCredentials` in `src/omc_analytics/common/models.py`
- [ ] 1.2 Add `@field_validator("pii_salt")` auto-generating `uuid4().hex` if None
- [ ] 1.3 Create `tests/unit/common/test_models.py` — salt auto-gen, immutability, length validation
- [ ] 1.4 Extend `tests/unit/common/test_kms_secrets.py` — round-trip preserves `pii_salt`
- [ ] 1.5 Run `uv run pytest tests/unit/common/ -v` — all green

## Phase 2: salted_hash macro + silver_orders delta + dbt tests

- [ ] 2.1 Create `dbt_project/macros/salted_hash.sql` — macro taking `(column_name, salt_var='pii_salt')`
- [ ] 2.2 Add `vars.pii_salt: "{{ env_var('OMCAE_PII_SALT') }}"` to `dbt_project/dbt_project.yml`
- [ ] 2.3 Add 2 salted columns to `silver_orders.sql` final SELECT using `{{ salted_hash(...) }}`
- [ ] 2.4 Add column definitions + `not_null` tests to `silver_orders.yml`
- [ ] 2.5 Create `dbt_project/tests/silver_orders_salted_hash_stable.sql` custom singular test
- [ ] 2.6 Compile: `OMCAE_PII_SALT=test-salt uv run dbt compile --project-dir dbt_project`
- [ ] 2.7 Run existing dbt tests: `OMCAE_PII_SALT=test-salt uv run dbt test --project-dir dbt_project`

## Phase 3: Integration test + docs

- [ ] 3.1 Create `tests/integration/test_dbt_pii_salted.py` — mirror e2e pattern + assert salted columns
- [ ] 3.2 Add `OMCAE_PII_SALT` to `.env.example`
- [ ] 3.3 Update `README.md` with PII salt env var docs
- [ ] 3.4 Run full suite: `uv run ruff check && uv run mypy src/omc_analytics && uv run pytest`
