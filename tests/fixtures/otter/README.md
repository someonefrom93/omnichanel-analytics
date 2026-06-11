# Otter API Fixtures

JSON fixtures derived from ReDoc samples at https://developer-guides.tryotter.com/api-reference/.

## Source Tagging

Each fixture carries three metadata fields (our additions, not Otter's):

```json
{
  "source": "redoc-sample",
  "version": "1.0",
  "endpoint": "<method> /v1/<path>",
  ...Otters response fields...
}
```

- `source`: Always `"redoc-sample"` — indicates the fixture was built from
  ReDoc documentation, not a live network capture.
- `version`: Pinned to `"1.0"`. If the Otter API changes, copy the file
  to a new versioned fixture rather than mutating the existing one.
- `endpoint`: The exact method and path this fixture simulates. Used by
  `test_fixtures.py` for naming-convention validation.

## Files

| File | Endpoint | Description |
|------|----------|-------------|
| `orders_response.json` | `GET /v1/orders` | Paginated order list — 2 sample orders |
| `reports_enqueue_response.json` | `POST /v1/reports` | Job enqueue confirmation — QUEUED |
| `reports_result_ready.json` | `GET /v1/reports/{jobId}` | Terminal READY state with result payload |
| `oauth_token_response.json` | `POST /v1/auth/token` | Token grant response — client_credentials flow |

## Usage in Tests

Use `load_fixture()` from `tests/conftest.py` (or inline) to strip the metadata
and use the raw Otter response:

```python
import json, responses

def load_fixture(name: str) -> dict:
    path = Path(__file__).parent / f"{name}.json"
    raw = json.loads(path.read_text())
    return {k: v for k, v in raw.items()
            if k not in ("provenance", "fixture_version", "endpoint")}

@responses.activate
def test_something():
    payload = load_fixture("orders_response")
    responses.add(responses.GET, ".../v1/orders", json=payload, status=200)
    ...
```

## Version Policy

- `fixture_version` is always `"1.0"` in PR1.
- When the Otter API surface changes (PR2+), create `orders_response_v2.json`
  rather than editing the existing file.
- The `test_fixtures.py` validation suite will flag any file whose
  `fixture_version` does not match the current pinned version.