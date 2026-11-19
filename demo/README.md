# Demo service

The backend of `sdk-kit new demo` and of the Docker scenario `core.health`: a Python
standard-library HTTP server (`server.py`, image `python:3.13.18-alpine3.24`, user 10001) that serves
exactly the paths of the skeleton client every generated SDK starts with.

| Request | Answer |
| - | - |
| `GET /health` | `200 {"status":"ok"}` (no authentication) |
| `GET /v1/ping` + `Authorization: Bearer <DEMO_TOKEN>` | `200 {"pong":true}`; otherwise `401 {"error":"unauthorized"}` + `WWW-Authenticate` |
| `GET /version` | `200 {"version":"<DEMO_VERSION>"}` |
| other paths / methods | `404 {"error":"not_found"}` / `405 {"error":"method_not_allowed"}` + `Allow` |

Every response has `x-request-id: demo-<n>`.

## Test controls (disable with `DEMO_CONTROLS=0`)

| Request | Effect |
| - | - |
| `POST /__fault` | queue faults for the next service requests; body = one object or a list |
| `GET /__fault` / `DELETE /__fault` | list / clear queued faults |
| `GET /__requests` / `DELETE /__requests` | last 200 requests (method, path, query, headers with secrets redacted, request id) / clear |
| `GET /__stats` | `{"total": n, "paths": {"/health": n, …}}` |
| `POST /__reset` | clear faults, requests and counters |

Fault fields: `status` (default 503), `count` (1), `path` (default: every service path), `method`,
`retryAfter` (sent as `Retry-After`), `delayMs` (sleep first, ≤ 120000 — for timeout tests),
`body` (JSON, default `{"error":"fault"}`), `headers`, `reset` (`true` = close the connection
without an answer — a network error). Example: two 503s then a 429 with `Retry-After: 1`:

```sh
curl -X POST "$GROW_DEMO_URL/__fault" -d '[{"status":503,"count":2},{"status":429,"retryAfter":"1"}]'
```

Environment: `DEMO_PORT` (8080), `DEMO_HOST` (0.0.0.0), `DEMO_TOKEN` (`demo-token`; the compose file
sets `demo-local-token`), `DEMO_VERSION` (`1.0.0`), `DEMO_CONTROLS` (1), `DEMO_LOG` (0).
`python server.py --healthcheck` exits 0 when the local `/health` answers 200.

In a generated `demo` repository this folder is `docker/demo/`; `compose.service.yml` and
`bootstrap/bootstrap.sh` become `docker/compose.service.yml` and `docker/bootstrap/bootstrap.sh`.
Tests (sdk-kit only): `pytest demo/tests --cov=server --cov-branch` (100 % lines and branches).
