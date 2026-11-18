# Better Stack Logs stub (contract-verified)

Better Stack Logs is SaaS only, so the `better-stack-logs` SDK's Docker suite runs against this stub:
a Python standard-library server (`stub.py`, `sql.py`, `otlp.py`, `msgpack_decode.py`) with two
listeners, like the real service's two hosts.

| Listener | Port | Real counterpart |
| - | - | - |
| ingest | 8080 (`BETTERSTACK_STUB_INGEST_PORT`) | `https://$INGESTING_HOST` (per-source ingesting host) |
| query | 8123 (`BETTERSTACK_STUB_QUERY_PORT`) | `https://<region>-connect.betterstackdata.com` (SQL API, ClickHouse HTTP) |

Files for a generated repo: `compose.service.yml` → `docker/compose.service.yml`, `bootstrap.sh` →
`docker/bootstrap/bootstrap.sh`, the four `.py` files + `Dockerfile` + `.dockerignore` →
`docker/betterstack-stub/` (see `../GENERATOR_NOTES.md`). The bootstrap writes
`BETTERSTACK_SOURCE_TOKEN`, `BETTERSTACK_INGESTING_HOST` (`host:port`), `BETTERSTACK_INGESTING_URL`,
`BETTERSTACK_QUERY_HOST`, `BETTERSTACK_QUERY_URL`, `BETTERSTACK_QUERY_USERNAME`,
`BETTERSTACK_QUERY_PASSWORD` and `BETTERSTACK_SOURCE_TABLE` (`t1_grow_conformance`) to
`/bootstrap/env`.

## Behaviour verified against public documentation (checked 2026-11-18)

Sources:
[A] Better Stack "Ingesting logs" HTTP API — <https://betterstack.com/docs/logs/ingesting-data/http/logs/>
[B] Better Stack "SQL API" / connect remotely — <https://betterstack.com/docs/logs/query-api/connect-remotely/>
[C] Better Stack "OpenTelemetry" — <https://betterstack.com/docs/logs/open-telemetry/>
[D] Better Stack's own Node.js client `@logtail/node` — <https://github.com/logtail/logtail-js/blob/master/packages/node/src/node.ts>
[E] ClickHouse HTTP interface — <https://clickhouse.com/docs/interfaces/http>
[F] OTLP/HTTP specification — <https://opentelemetry.io/docs/specs/otlp/#otlphttp>

| Behaviour | Source |
| - | - |
| `POST /`, `Authorization: Bearer <source token>` required | A |
| `Content-Type` `application/json`, `application/msgpack` or `application/x-ndjson` | A |
| body = one event object or an array of events (JSON, MessagePack, NDJSON lines) | A |
| `202` with empty body on success | A |
| `403` body `Unauthorized` for an invalid source token | A |
| `406` body `Couldn't parse JSON content.` for a body that is not valid JSON/MessagePack | A |
| `413` body `payload reached size limit` over 10 MiB per request, measured compressed | A |
| `402` body `Quota exceeded` (quota / spending limit) — only via the fault control | A |
| each record at most 10 MiB uncompressed | A |
| `dt`: UNIX seconds, milliseconds or nanoseconds; RFC 3339 strings (`T` or space separator, `Z` or offset); ISO 8601; MessagePack timestamp extension; unparseable → kept as a string in the record, event time = reception time; no `dt` → reception time | A |
| `Content-Encoding: gzip` on the raw ingest endpoint (Better Stack's own client sends gzipped MessagePack) | D |
| OTLP/HTTP on the ingesting host: `/v1/logs`, `/v1/traces`, `/v1/metrics`, same Bearer token, gzip | C |
| OTLP protobuf (`application/x-protobuf`) and JSON (`application/json`), 200 + empty `Export…ServiceResponse`, `415` for other media types, `400` for undecodable payloads | F |
| SQL API: `POST` the query as body, HTTP basic auth, `?output_format_pretty_row_numbers=0` accepted | B |
| sources `remote(<t>_logs)` (hot), `remote(<t>_spans)`, `remote(<t>_metrics)`, `s3Cluster(primary, <t>_s3)` with `_row_type` (cold), `UNION ALL` of hot + cold, columns `dt` + `raw` | B |
| `WHERE raw LIKE '%text%'`, `JSONExtract(raw, 'key', 'Nullable(String)')`, `ORDER BY dt`, `LIMIT`, `toDateTime64(epoch, 0, 'UTC')`, `BETWEEN`, `FORMAT JSONEachRow / JSON / CSV / TSV`, `SETTINGS output_format_json_array_of_rows = 1` | B |
| ClickHouse HTTP conventions: `?query=` + body concatenation, `X-ClickHouse-User`/`X-ClickHouse-Key` or `user`/`password` parameters, `default_format`, `{name:Type}` placeholders bound from `param_<name>`, `SELECT` without `FROM`, `/ping` → `Ok.`, error body `Code: N. DB::Exception: … (NAME)`, `X-ClickHouse-Exception-Code`, `X-ClickHouse-Format`, default output `TabSeparated`, (U)Int64 quoted in JSON formats | E |

## Stub choices (not verifiable from public docs — confirm with a live source)

- `405` for non-`POST` on `/`, `404` for other ingest paths, `415` for an unknown `Content-Encoding`,
  `406` for a missing/unknown `Content-Type` (docs: header is required, status not stated), `400`
  for a broken `Content-Length` or chunked encoding.
- An oversized body is read and discarded (up to 64 MiB) before the `413`, so clients can finish
  writing and read the answer; the real service may close earlier. SDKs must never send > 10 MiB.
- The order of checks: size → token (403) → fault → encoding → content type → body.
- The stored `raw` value is the event JSON as received (MessagePack timestamps become RFC 3339
  strings, non-UTF-8 `bin` becomes base64). Whether Better Stack adds or rewrites fields in `raw`
  (for example `dt`) is undocumented.
- OTLP logs are stored as `{"dt", "message", "level", "severity_number", "attributes", "resource",
  "scope", "trace_id", "span_id", "event_name"}`; Better Stack's internal mapping of OTLP logs is
  undocumented. OTLP traces and metrics are accepted and discarded.
- `dt` in query results is `DateTime64(6)` UTC text (`2026-11-18 12:00:00.123456`); nanoseconds are
  truncated with integer arithmetic. UNIX microseconds (16 digits) are accepted too.
- Query authentication failure answers `401` with ClickHouse code 516 (ClickHouse maps
  `AUTHENTICATION_FAILED` to 401; Better Stack's proxy may differ). Error HTTP status follows
  ClickHouse's mapping: unknown table/column/function/format → 404, `NOT_IMPLEMENTED` → 501,
  syntax and parameter errors → 400.
- Cold storage (`s3Cluster`) and spans are always empty: every stub record is "hot".
- `JSONExtract` also accepts dotted keys (`'context.hostname'`) as a nested path, as the Better
  Stack examples use them; plain ClickHouse treats the dot literally.
- `version()` returns `24.8.0.0-betterstack-stub`.
- Not modelled: rate limits (docs: 4 concurrent log queries per connection), the 10-day hot
  window, `S3 sampling`, `GROUP BY`/aggregates other than `count()`, team/connection scoping.

## SQL subset

`SELECT <* | expr [AS alias], …> [FROM remote(t) | s3Cluster(c, t[, opts]) | (<select> UNION ALL …)]
[WHERE …] [ORDER BY expr [ASC|DESC], …] [LIMIT n [OFFSET m] | LIMIT m, n] [SETTINGS k = v, …]
[FORMAT …]`. Operators `= != <> < <= > >=`, `[NOT] LIKE`, `[NOT] ILIKE`, `[NOT] BETWEEN`,
`[NOT] IN (…)`, `IS [NOT] NULL`, `AND OR NOT`, `+ -` with `INTERVAL n SECOND|MINUTE|HOUR|DAY|WEEK`.
Functions: `count()`, `JSONExtract`, `JSONExtractString|Int|UInt|Float|Bool|Raw`, `JSONHas`,
`toDateTime`, `toDateTime64`, `now`, `version`, `lower`, `upper`, `toString`, `length`, `position`,
`positionCaseInsensitive`. Query parameter types: `String`, `FixedString`, `UUID`, `Enum*`,
`LowCardinality`, `(U)Int*`, `Float*`, `Decimal*`, `Bool`, `Date`, `DateTime`, `DateTime64`,
`Identifier`, `Nullable(…)` (`\N` = NULL). Anything else fails with a ClickHouse error code.

## Stub controls (both ports; not part of the real API)

| Request | Effect |
| - | - |
| `GET /__stub/health` | `{"status":"ok","role":"ingest"|"query"}` |
| `GET /__stub/records[?table=t]` | stored records (`table`, `dt`, `raw`, `received`) |
| `DELETE /__stub/records` | drop all records |
| `GET /__stub/requests` | last 500 requests (content type/encoding, bytes, records, status; never tokens) |
| `POST /__stub/fault` | `{"status": 429, "count": 1, "target": "ingest"|"query", "body": "…", "retryAfter": 2, "headers": {…}}` — the next `count` authenticated requests get this answer |
| `DELETE /__stub/fault` | clear faults |
| `POST /__stub/reset` | clear records, requests and faults |

Environment: `BETTERSTACK_STUB_SOURCES` (`token=table,…`, default
`stub-source-token=t1_grow_conformance`), `BETTERSTACK_STUB_QUERY_USER` / `_PASSWORD`
(`stub-user` / `stub-password`), `BETTERSTACK_STUB_HOST`, `BETTERSTACK_STUB_MAX_REQUEST_BYTES`
(10 MiB), `BETTERSTACK_STUB_MAX_RECORD_BYTES` (10 MiB), `BETTERSTACK_STUB_MAX_RECORDS` (100000),
`BETTERSTACK_STUB_LOG`.

## Tests

```sh
python -m venv .venv && .venv/bin/pip install pytest pytest-cov
.venv/bin/pytest harness/betterstack-stub/tests --cov=stub --cov=sql --cov=otlp --cov=msgpack_decode --cov-branch
```
