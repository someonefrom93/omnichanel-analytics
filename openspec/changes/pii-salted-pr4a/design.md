# Design: pii-salted-pr4a

## Technical Approach

Add `MerchantCredentials.pii_salt` (auto-gen UUID4), a `salted_hash` dbt macro
using DuckDB `hash()` (xxhash64), and two new salted PII columns on
`silver_orders`. Raw columns preserved. Salt from `OMCAE_PII_SALT` env var.

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Hash primitive | DuckDB `hash()` (xxhash64) | No extension needed; deterministic; non-cryptographic but meets per-merchant stable ID goal |
| Salt field type | `str \| None` with auto-gen | UUID4 hex; 32-char; wide enough for per-merchant entropy |
| Auto-gen trigger | Pydantic `@field_validator('pii_salt')` in `after` mode | Runs on construction, not on model_dump; avoids circular dep |
| Salt source | `var('pii_salt')` from `OMCAE_PII_SALT` env var | Build-time single salt; per-merchant via SecretsPort is PR5 |
| Schema evolution | `on_schema_change='append_new_columns'` | Already active in silver_orders config; columns auto-added |
| Raw columns | Preserved | Back-compat for PR5 UI (customer lookup per merchant) |

## Data Flow

```
OMCAE_PII_SALT (env var)
         │
         ▼
  dbt_project.yml ──→ var('pii_salt')
         │
         ▼
  salted_hash macro ──→ hash(salt || raw_hash) ──→ silver_orders
         ▲
  customer_name_hash ─┘  customer_phone_hash ─┘
  (raw, from Bronze)      (raw, from Bronze)
```

## File Changes

| File | Action | LOC |
|------|--------|-----|
| `src/omc_analytics/common/models.py` | Modify — add `pii_salt: str \| None` + validator | +15 |
| `dbt_project/macros/salted_hash.sql` | Create | 10 |
| `dbt_project/models/silver/silver_orders.sql` | Modify — add 2 salted columns in SELECT | +4 |
| `dbt_project/models/silver/silver_orders.yml` | Modify — add 2 columns + not_null tests | +15 |
| `dbt_project/tests/silver_orders_salted_hash_stable.sql` | Create | 20 |
| `dbt_project/dbt_project.yml` | Modify — add `vars.pii_salt` | +3 |
| `tests/unit/common/test_models.py` | Create — salt auto-gen + immutability tests | 45 |
| `tests/unit/common/test_kms_secrets.py` | Modify — round-trip with `pii_salt` | +25 |
| `tests/integration/test_dbt_pii_salted.py` | Create | 85 |
| `.env.example` | Modify — `OMCAE_PII_SALT` | +5 |
| `README.md` | Modify — env var docs | +10 |

**Total: ~237 LOC** (under 280 forecast, under 400-line budget).

## Interfaces / Contracts

### MerchantCredentials delta
```python
from uuid import uuid4
from pydantic import field_validator

class MerchantCredentials(BaseModel):
    ...
    pii_salt: str | None = Field(default=None, min_length=32, max_length=32)
    
    @field_validator("pii_salt", mode="after")
    @classmethod
    def _generate_salt_if_missing(cls, v: str | None) -> str:
        if v is None:
            return uuid4().hex  # 32 chars, no hyphens
        if len(v) != 32:
            raise ValueError("pii_salt must be 32 hex chars")
        return v
```

### salted_hash macro
```sql
{% macro salted_hash(column_name, salt_var='pii_salt') %}
    hash({{ var(salt_var) }} || {{ column_name }})
{% endmacro %}
```

### silver_orders SELECT delta
```sql
-- Add after existing customer_phone_hash:
{{ salted_hash('customer_name_hash') }} as customer_name_hash_salted,
{{ salted_hash('customer_phone_hash') }} as customer_phone_hash_salted
```

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit — models | Salt auto-gen, immutability, round-trip | pytest + Pydantic model validation |
| Unit — KMS | Round-trip preserves pii_salt | Extend existing test fixture |
| dbt test | not_null on salted columns | YAML schema test |
| dbt test | Stability (idempotency) | Custom singular test |
| Integration | Full dbt build with moto S3 + OMCAE_PII_SALT | Mirror test_dbt_silver_orders_e2e.py pattern |

## Migration

- First `dbt run --select silver_orders` auto-adds salted columns via `append_new_columns`.
- Existing rows get salted hashes computed from raw hash + salt.
- `--full-refresh` NOT required for column add (append_new_columns handles it).
- Rollback: remove salted columns from model SQL → `dbt run --full-refresh` drops them.

## Open Questions

None — all design forks resolved in umbrella proposal.
