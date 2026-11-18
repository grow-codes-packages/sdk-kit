# Datadog fakeintake

`datadog/fakeintake` is Datadog's own test intake (source:
<https://github.com/DataDog/datadog-agent/tree/main/test/fakeintake>, Apache-2.0). It is the
service under test for `datadog-logs` and the backend of the `datadog/agent` used by `datadog-apm`.

Pinned image: `datadog/fakeintake:v74@sha256:d84716ff38703cefa7fb5b822cfcd421d18822e8a85606466af771969289963e`
(published 2026-11-10; tags `vNN` are build numbers, the digest keeps the pin immutable).

Files for a generated repo: `compose.service.yml` → `docker/compose.service.yml`, `bootstrap.sh` →
`docker/bootstrap/bootstrap.sh`, `fakeintake.py` → `docker/harness/fakeintake.py`.

## What it accepts (from `test/fakeintake/server/server.go`, checked 2026-11-18)

- **Any `POST` path** is stored as a raw payload under that path (body, `Content-Encoding` — or
  `Content-Type` when no encoding is sent —, the API key from `DD-API-KEY` or `?api_key=`, time).
  The default answer is `200 {"errors":[]}`; the real intakes answer `202`. `bootstrap.sh` sets an
  override so `/api/v2/logs` answers `202 {}` like the real Logs intake.
- **Logs:** `POST /api/v2/logs` (the Logs HTTP intake path, `https://http-intake.logs.<site>/api/v2/logs`).
  `GET /fakeintake/payloads?endpoint=/api/v2/logs&format=json` parses JSON arrays of logs, gzip,
  deflate or zstd, but keeps only `message`, `status`, `timestamp`, `hostname`, `service`,
  `ddsource`, `ddtags`. Use `fakeintake.py logs` (raw payloads, all attributes).
- **APM traces:** the Datadog Agent's trace writer sends `POST /api/v0.2/traces` (protobuf
  `AgentPayload`, compressed per `Content-Encoding`) and stats to `/api/v0.2/stats`. fakeintake stores
  them as raw payloads (no `format=json` parser for traces); its Go client decodes them with
  `aggregator.ParseTracePayload`. SDK tests for `datadog-apm` should assert on the agent side
  (OTLP receiver accepted the spans) and count `/api/v0.2/traces` payloads, or decode the protobuf.
  Run the agent with `DD_DD_URL=http://fakeintake`, `DD_APM_DD_URL=http://fakeintake`,
  `DD_OTLP_CONFIG_RECEIVER_PROTOCOLS_HTTP_ENDPOINT=0.0.0.0:4318`,
  `DD_OTLP_CONFIG_RECEIVER_PROTOCOLS_GRPC_ENDPOINT=0.0.0.0:4317`, any `DD_API_KEY`.
- **Control API:** `GET /fakeintake/health`, `GET /fakeintake/payloads?endpoint=<path>[&format=json]`,
  `GET /fakeintake/routestats`, `GET /fakeintake/flushPayloads`,
  `POST /fakeintake/configure/override` (`{"endpoint","method","status_code","content_type","body"}`,
  `body` is base64 because it is a Go `[]byte`), `GET /debug/lastAPIKey/`.
- No API-key validation, no query API (Logs Search / APM query endpoints are not emulated); payloads
  are kept 15 minutes by default (`-retention-period 30m` in the compose file).

## `fakeintake.py`

Python standard library helper (module + CLI); base URL from `--url` or `FAKEINTAKE_URL`:
`health`, `routes`, `payloads <path> [--reveal]`, `logs [--contains T] [--service S]`,
`wait <path> [--min N] [--contains T] [--timeout S]`, `override <path> <status> [--body] [--method]`,
`flush`, `last-api-key [--reveal]`. API keys are masked unless `--reveal`.

Tests: `pytest harness/fakeintake/tests --cov=fakeintake --cov-branch`.
