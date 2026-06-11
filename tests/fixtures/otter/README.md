# Otter API Test Fixtures

This directory contains JSON fixtures derived from the Otter Public API
reference documentation (developer-guides.tryotter.com). These fixtures are
used by `responses`-based unit tests and moto-S3 integration tests to avoid
hitting the live API during CI.

## Fixture Naming Convention

Each fixture file should be named to reflect the API endpoint or response
type it represents:

- `orders_sample.json` — GET /v1/orders response
- `oauth_token_sample.json` — POST /v1/auth/token response
- `reports_enqueue_sample.json` — POST /v1/reports response (job enqueue)
- `reports_result_sample.json` — GET /v1/reports/{jobId} result payload

## Required Metadata Tags

Every fixture MUST carry two top-level identifying fields:

```json
{
  "source": "redoc-sample",
  "version": "1.0",
  ...
}
```

| Field   | Value          | Meaning                                            |
|---------|----------------|----------------------------------------------------|
| `source` | `redoc-sample` | Fixture derived from Otter API reference docs      |
| `version` | `1.0`         | Schema version — bump when API shape changes       |

The `source` tag enables filtering fixtures by origin in tests.
The `version` tag enables migration when the API evolves.

## Fixture Content Rules

1. **Do not modify** fixture content to match test expectations — tests
   must adapt to the documented API shape, not the other way around.
2. **Do not add fixtures** for this directory without the `source` and
   `version` tags. Untagged fixtures will fail CI.
3. **Do not commit real credentials** — fixtures contain only synthetic
   sample data derived from the API reference.
4. **Version bump** when the Otter API adds breaking changes — update the
   `version` field and create a new fixture file if the schema changes.

## Loading Fixtures in Tests

Use the helper in `tests/conftest.py` or load directly:

```python
import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "otter"

def load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / name
    with open(path) as fh:
        return json.load(fh)
```

## CI / Network Isolation

`pytest` runs against these fixtures via `responses.RequestsMock()`.
No real HTTP calls to `api.otter.dev` should occur during the test suite.
If a test makes a real network call, it will fail with a `ConnectionError`.