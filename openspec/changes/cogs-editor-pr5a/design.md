# Design: COGS Editor + Streamlit Scaffolding (PR5a)

## Technical Approach

Streamlit multi-page app with `serving/streamlit_app.py` entry, `serving/pages/cogs_editor.py`
page. DuckDB-backed `GoldReader` for reads (reuses dbt-duckdb Gold layer). `CogsWriter`
mirrors `PostgresLogs` pattern: psycopg2 `ThreadedConnectionPool` + `_acquire` context manager,
`connection_factory` injection. Dev backend selection via `OMCAE_COGS_BACKEND` env var.

## Architecture Decisions

| # | Decision | Choice | Rejected | Rationale |
|---|----------|--------|----------|-----------|
| 1 | Page router | `st.navigation` (multi-page) | `st.Page` manually, single-page with state | Streamlit 1.32 native multi-page, simpler routing |
| 2 | Read backend | DuckDB `read_parquet` on Gold dir | Raw S3 reads, Postgres views | Reuses existing dbt-duckdb; zero new infra |
| 3 | Write backend | psycopg2 pool (mirrors `PostgresLogs`) | SQLAlchemy, raw `psycopg2.connect` | Consistent pattern; pool safe for Streamlit threads |
| 4 | Tenant fence | Mandatory `merchant_id` arg on every method | Decorator, context manager | Compile-time `TypeError` if missing; simplest |
| 5 | Dev fallback | `OMCAE_COGS_BACKEND=memory` → dict stub | Separate class hierarchy | Mirrors `OMCAE_LOGS_BACKEND` pattern from ingestion |

## Data Flow

```
st.sidebar.text_input("merchant_id")
        │
        ▼
st.session_state.merchant_id
        │
        ├──► GoldReader(merchant_id).list_menu_items()
        │         │
        │         ▼ DuckDB read_parquet(Gold/dim_menu_catalog)
        │         ▼ return menu rows scoped to merchant
        │
        └──► CogsWriter(connection_factory).upsert(...)
                  │
                  ▼ psycopg2 INSERT ON CONFLICT → PostgreSQL merchant_cogs
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Modify | Add `streamlit>=1.32.0` runtime dep; add `streamlit` to mypy overrides |
| `src/omc_analytics/serving/__init__.py` | Modify | Extend docstring |
| `src/omc_analytics/serving/streamlit_app.py` | Create | Entry: `st.set_page_config`, sidebar merchant text input, `st.navigation` |
| `src/omc_analytics/serving/data_access.py` | Create | `GoldReader(merchant_id)`: list_menu_items, list_merchant_cogs (DuckDB) |
| `src/omc_analytics/serving/cogs_writer.py` | Create | `CogsWriter(connection_factory)`: upsert, delete (psycopg2 pool) |
| `src/omc_analytics/serving/pages/__init__.py` | Create | Package init |
| `src/omc_analytics/serving/pages/cogs_editor.py` | Create | `st.data_editor` over menu items + Save → CogsWriter.upsert |
| `src/omc_analytics/common/migrations/002_create_merchant_cogs.sql` | Create | Idempotent DDL |
| `tests/unit/serving/test_data_access.py` | Create | GoldReader unit tests |
| `tests/unit/serving/test_cogs_writer.py` | Create | CogsWriter unit tests (psycopg2 + testcontainers) |
| `tests/unit/serving/test_migration_002_ddl.py` | Create | DDL idempotency test (mirrors test_migration_ddl.py) |
| `tests/unit/serving/test_streamlit_app.py` | Create | AppTest scenarios for editor flow |

## Interfaces

```python
# GoldReader — mandatory merchant_id on every method
class GoldReader:
    def __init__(self, merchant_id: str, duckdb_path: str | None = None) -> None: ...
    def list_menu_items(self, merchant_id: str) -> list[dict]: ...
    def list_merchant_cogs(self, merchant_id: str) -> list[dict]: ...

# CogsWriter — mirrors PostgresLogs injection pattern
class CogsWriter:
    def __init__(self, connection_factory: Callable[[], psycopg2.extensions.connection],
                 min_conn: int = 0, max_conn: int = 5) -> None: ...
    def upsert(self, merchant_id: str, line_item_sku: str,
               recipe_cost: float, packaging_cost: float) -> None: ...
    def delete(self, merchant_id: str, line_item_sku: str) -> None: ...
```

## DDL: 002_create_merchant_cogs.sql

```sql
CREATE TABLE IF NOT EXISTS merchant_cogs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id    TEXT NOT NULL,
    line_item_sku  TEXT NOT NULL,
    recipe_cost    DECIMAL(10,4) NOT NULL DEFAULT 0,
    packaging_cost DECIMAL(10,4) NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (merchant_id, line_item_sku)
);
CREATE INDEX IF NOT EXISTS idx_merchant_cogs_merchant
    ON merchant_cogs (merchant_id);
```

## Testing Strategy

| Layer | What | How |
|-------|------|-----|
| Unit | DDL idempotency | SQLite in-memory via adapter (mirrors test_migration_ddl.py) |
| Unit | CogsWriter upsert/delete | `psycopg2` + testcontainers postgres; pool acquire/release |
| Unit | GoldReader tenant fence | DuckDB in-memory with temp table seeding |
| Integration | Editor flow | `AppTest.from_file` with real Streamlit session, seeded DuckDB |
| Quality | ruff, mypy, black | `uv run ruff check`, `uv run mypy src/omc_analytics`, `uv run black --check .` |

**AppTest scenarios**: (1) full editor flow — load, edit cell, click Save, verify upsert called; (2) merchant fence — empty merchant_id shows redirect message.

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| `st.data_editor` returns null for unedited cells | Filter `session_state` delta before calling upsert |
| ThreadedConnectionPool exhaustion under concurrent users | `max_conn=5` per worker; App Runner auto-scales |
| DuckDB S3 HTTPFS creds at app start | Lazy-connect on first read; PR5b adds Tier 1/2/3 banner |

## Open Questions

None — all decisions locked per pre-approved proposal.
