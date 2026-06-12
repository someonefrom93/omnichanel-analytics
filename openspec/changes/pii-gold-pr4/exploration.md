# Exploration: pii-gold-pr4

## Current State

The Silver tier from PR3 (`silver_orders`, `silver_reports`) materializes the raw
Otter API payload. PII columns (`customer_name_hash`, `customer_phone_hash`) are
copied **raw** (no salt) per the PR3 design decision to keep Silver stable and
defer salting to PR4. The Gold tier (`fact_financial_sales`, `dim_menu_catalog`)
does not exist. `merchant_cogs` is referenced in `dbt_project.yml` as a target
PostgreSQL source but has no seed, no schema, no test.

`MerchantCredentials` (Pydantic, in `src/omc_analytics/common/models.py`) is a
frozen model holding `merchant_id`, OAuth tokens, and the encrypted client
secret. There is **no** `pii_salt` field yet. The SecretsPort
(`KMSSecrets` + `InMemorySecrets`) round-trips the entire `MerchantCredentials`
JSON through AES-256-GCM, so adding a field is additive but requires a
`MerchantCredentials` rehydration test.

The dbt-duckdb profile (dbt 1.11.11 / dbt-duckdb 1.10.1) already has the
`incremental+merge` pattern wired with composite `unique_key` and
`on_schema_change='append_new_columns'`. The PR3 deviation block in
`silver_orders.sql` (lines 50–69) shows the project learned to use
`OMCAE_USE_LOCAL_BRONZE=true` to bypass S3 httpfs in tests by pre-creating the
`bronze.orders` table. This same mechanism is the cheapest path for the
`merchant_cogs` stub in PR4.

## Affected Areas

| File / Area | Why it changes |
|---|---|
| `src/omc_analytics/common/models.py` | Add `pii_salt: str \| None` to `MerchantCredentials` |
| `dbt_project/macros/salted_hash.sql` | NEW — `salted_hash(column, salt)` macro for SHA-256 hash of `salt \|\| value` |
| `dbt_project/models/silver/silver_orders.sql` | Add `customer_name_hash_salted`, `customer_phone_hash_salted` columns; use `salted_hash` |
| `dbt_project/models/silver/silver_orders.yml` | Document new salted columns; add `not_null` tests once salt is provisioned |
| `dbt_project/tests/silver_orders_salted_hash_stable.sql` | NEW — deterministic test: same input + same salt → same output |
| `dbt_project/seeds/merchant_cogs_seed.csv` | NEW — seed: `merchant_id, line_item_sku, recipe_cost_minor, packaging_cost_minor` |
| `dbt_project/seeds/_seeds.yml` | NEW — column types + `not_null` on `(merchant_id, line_item_sku)` |
| `dbt_project/models/gold/_sources.yml` | NEW — `gold_seeds.merchant_cogs` source |
| `dbt_project/models/gold/dim_menu_catalog.sql` | NEW — composite PK `(merchant_id, line_item_sku)`; incremental+merge |
| `dbt_project/models/gold/dim_menu_catalog.yml` | NEW — schema + composite unique test |
| `dbt_project/models/gold/fact_financial_sales.sql` | NEW — composite PK `(merchant_id, order_id, source_marketplace, line_item_sku)`; joins silver_orders + dim_menu_catalog + merchant_cogs |
| `dbt_project/models/gold/fact_financial_sales.yml` | NEW — schema + tests for the 4 net-margin columns |
| `dbt_project/dbt_project.yml` | Add `vars: { merchant_salt: "{{ env_var('OMCAE_PII_SALT', '') }}", default_commission_bps: 1500 }` |
| `dbt_project/profiles.yml` | Add `gold` schema defaults + ensure `gold_seeds` schema is reachable for the seed |
| `tests/unit/common/test_models.py` | NEW — assert `pii_salt` is auto-generated on save when absent |
| `tests/unit/common/test_kms_secrets.py` | Modify — round-trip with `pii_salt` populated |
| `tests/integration/test_dbt_pii_salted.py` | NEW — moto S3 + temp DuckDB + `dbt build --select silver_orders` + assert salted columns |
| `tests/integration/test_dbt_gold_star_schema.py` | NEW — seed merchant_cogs + run gold models + assert margin arithmetic |
| `tests/fixtures/merchant_credentials_with_salt.json` | NEW — fixture merchant with provisioned `pii_salt` |
| `dbt_project/dev.duckdb` | Reset target — Gold writes new schemas |
| `README.md` | Document PII salt provisioning, gold layer, env var `OMCAE_PII_SALT` |

## Approaches

### Fork 1 — Hashing primitive for the SaltedHash macro

| Option | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A. DuckDB built-ins (`md5` + concat)** | Use `md5(salt \|\| column)` | Zero Python deps; deterministic; dbt compiles cleanly | MD5 not SHA-256; PRD §3.2 mandates SHA-256 | Low |
| **B. `cryptography` Python UDF in a dbt macro** | Pre-compute the hash in Python, pass via `var()` | True SHA-256; matches PRD literally | Pre-computation requires loading all rows into Python; defeats set-based dbt | Med |
| **C. DuckDB community `hash` extension (SHA-256)** | Use a community extension like `blurryblurry/duckdb_sha256` (or write a simple C++ UDF) | True SHA-256, set-based, single SQL call | Extension must be bundled; pin to dbt-duckdb's DuckDB version; maintenance risk | Med |
| **D. dbt seed of static salt + DuckDB `hash` (`xxhash64`)** | Hash with xxhash64, accept PRD language drift | Simplest; no extensions | xxhash64 is not SHA-256; PRD violation; security reviewer pushback | Low |

**Recommendation: D with a documented deviation.** The PRD §3.2 says "salted
SHA-256", but the security goal is **stable, non-reversible, per-merchant
identifiers** — not cryptographic collision resistance against a nation-state.
The Bronze layer (PR1) already uses a raw SHA-256 from Otter; we're hashing
the hash anyway (defense in depth via per-merchant salt). xxhash64 of
`salt || raw_hash` meets the goal and avoids an extension dependency. Flag
this in the spec as a deviation; PR5+ can swap to true SHA-256 via a
DuckDB extension if compliance demands it.

### Fork 2 — Source for `merchant_cogs` in PR4

| Option | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A. dbt seed CSV** | `dbt_project/seeds/merchant_cogs_seed.csv` | Trivial; testable; no infra; version-controlled | Static; not writable from UI; replaced by PostgreSQL in PR5 | Low |
| **B. CTE in the Gold model** | Hard-coded `VALUES` block | Zero file overhead | Embedded in SQL; harder to maintain; tests still need dbt build | Low |
| **C. DuckDB attached PostgreSQL via `postgres_scanner`** | Real cross-source join | Closest to production shape | Requires running PG locally; CI hermeticity breaks; complex setup | High |
| **D. Pytest fixture that calls a stub function from a Python UDF** | Inject test COGS via dbt's `vars()` | Test-only | Production path is missing the real source | Med |

**Recommendation: A (dbt seed CSV) with B (CTE fallback in tests).** This matches
the existing `OMCAE_USE_LOCAL_BRONZE=true` deviation pattern: tests pre-create
the source table, production uses a different mechanism (the real PG table in
PR5). The seed lives in `dbt_project/seeds/`, gets `dbt seed`d, and is referenced
as `{{ ref('merchant_cogs_seed') }}` from `fact_financial_sales`.

### Fork 3 — Composite primary key for `dim_menu_catalog` in dbt-duckdb

| Option | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A. `unique_key=['merchant_id','line_item_sku']` (list form)** | Standard dbt list-form composite key | Already used in PR3 for `silver_orders`; verified working | DuckDB `merge` requires all keys to be in `merge_update_columns` for updates to flow; empty list defaults to "merge on key only" | Low |
| **B. Synthetic `_row_id` bigint + dbt `surrogate_key` test** | Generate a stable hash and use it as the unique key | Survives renames; test-friendly | Adds a column; not the natural key; deviates from PRD §3.2 (composite PK is the spec) | Med |
| **C. No `unique_key`; rely on a custom `unique` test for idempotency** | Append-only model; no merge | Simplest | Loses incremental-merge semantics; can't re-materialize without full refresh | Low |

**Recommendation: A.** Already proven in `silver_orders`; PR3 design.md locked it.
Add the composite unique test via custom singular SQL in
`dbt_project/tests/dim_menu_catalog_unique_combo.sql` (mirroring
`silver_orders_unique_order_marketplace.sql`).

### Fork 4 — `incremental+merge` with new columns on `silver_orders`

| Option | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A. `on_schema_change='append_new_columns'` (current setting)** | dbt auto-adds the new salted columns on subsequent runs | Already in place; minimal new code | Requires a re-run with `--full-refresh` the first time to backfill salt | Low |
| **B. `on_schema_change='sync_all_columns'`** | Drop + recreate | Auto-cleans | Destructive; might drop test columns; risky | Med |
| **C. Two separate models: `silver_orders_v1` + `silver_orders_v2`** | Versioned models | Zero risk to existing Silver | Table duplication; downstream must pick; messy | High |

**Recommendation: A.** The config block at `silver_orders.sql:6` already has
`on_schema_change='append_new_columns'`. Adding `customer_name_hash_salted` and
`customer_phone_hash_salted` to the SELECT clause is enough; dbt handles the
schema diff on the next run. First-time backfill requires `dbt run
--full-refresh --select silver_orders` because the merge filter is on
`created_at`, not on the salted columns.

## Recommendation

Two chained PRs:

- **PR4a (PII salted masking)**: Fork 1-D (xxhash64, PRD deviation documented) +
  Fork 4-A (append new columns). ~280 LOC.
- **PR4b (Gold star schema)**: Fork 2-A (dbt seed) + Fork 3-A (composite PK).
  ~320 LOC.

Combined forecast: ~600 LOC gross, exceeds 400. Chained PRs protect review
focus. Each PR is autonomously shippable, reversible, and rebaseable.

The xxhash64 deviation in PR4a must be flagged in the proposal's Risks +
documented in the spec under "Deviations from PRD §3.2." If the team insists
on real SHA-256, the fallback is a DuckDB community extension (Fork 1-C) at
~80 additional LOC and one extra dependency pin.

## Risks

- **xxhash64 vs SHA-256**: PR4a deviates from PRD §3.2 wording. If the security
  reviewer demands SHA-256, swap to Fork 1-C (DuckDB extension). +80 LOC, +1
  dependency.
- **`merchant_salt` provisioning**: dbt `vars: { merchant_salt:
  "{{ env_var('OMCAE_PII_SALT', '') }}" }` is a single env var, but the design
  says **per-merchant** salt. For PR4 we use a single env-var salt per build;
  per-merchant lookup is deferred to PR5 (Streamlit UI provisions salts via
  `SecretsPort`). Documented as a deviation.
- **Composite `unique_key` in dbt-duckdb merge**: confirmed working in PR3 but
  `dim_menu_catalog` introduces a new key shape (3-key composite in
  `fact_financial_sales`); edge case where one of the 4 keys is NULL breaks
  the merge. Add a `not_null` test on all 4 PK columns in the Gold yml.
- **Gold model volume**: `fact_financial_sales` is 1 row per (order, line
  item). With PR1's Bronze ingesting ~50–500 orders/merchant/day, the table
  grows linearly. No partition pruning in PR4; PR5 can add
  `partition_by: target_date` if volume warrants.
- **No UI to verify**: PR4 ships data marts with no consumer. Risk of schema
  drift between Gold and the future PR5 UI; mitigated by the spec contract
  (column names + types are part of the delta spec, so sdd-verify can enforce).

## Ready for Proposal

**Yes.** All design forks resolved against the existing PR3 patterns. The
PR4a/PR4b split is the natural cleavage: PII (secrets-touching) is logically
distinct from the Gold schema (data-modeling), and each PR is small enough
to review in one sitting.
