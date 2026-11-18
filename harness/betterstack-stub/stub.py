#!/usr/bin/env python3
"""Better Stack Logs intake + SQL query stub (Python standard library only).

Two listeners, like the real service's two hosts:

* **ingest** (``BETTERSTACK_STUB_INGEST_PORT``, default 8080) — ``POST /`` the way Better Stack's
  HTTP log ingestion API accepts it: ``Authorization: Bearer <source token>``, ``Content-Type``
  ``application/json`` | ``application/msgpack`` | ``application/x-ndjson``, a single event or an
  array of events, optional ``Content-Encoding: gzip``, ``dt`` timestamp rules, ``202`` on success,
  ``403 Unauthorized``, ``406 Couldn't parse JSON content.``, ``413 payload reached size limit``,
  ``402 Quota exceeded`` (via the fault control); plus OTLP/HTTP on the same host and token:
  ``POST /v1/logs`` (protobuf or JSON, logs stored as records), ``/v1/traces`` and ``/v1/metrics``
  (accepted, not stored).
* **query** (``BETTERSTACK_STUB_QUERY_PORT``, default 8123) — a ClickHouse HTTP interface with HTTP
  basic auth (or ``X-ClickHouse-User``/``X-ClickHouse-Key``, or ``user``/``password`` URL parameters)
  that answers the SQL subset in ``sql.py`` (incl. ``{name:Type}`` + ``param_<name>`` binding and
  ``SELECT`` without ``FROM``) over ``remote(<source>_logs)``,
  ``remote(<source>_spans)`` (always empty) and ``s3Cluster(primary, <source>_s3)`` (always empty:
  every stub record is "hot").

See README.md for exactly which behaviours are verified against Better Stack's public docs.

Stub controls (both listeners, never part of the real API): ``GET /__stub/health``,
``GET /__stub/records[?table=]``, ``DELETE /__stub/records``, ``GET /__stub/requests``,
``POST /__stub/fault`` (``{"status": 429, "count": 1, "target": "ingest"|"query", "body": "…",
"retryAfter": 2, "headers": {"X-Any": "v"}}``),
``DELETE /__stub/fault``, ``POST /__stub/reset``.

Environment (all optional):
``BETTERSTACK_STUB_SOURCES`` — comma separated ``token=table`` pairs
(default ``stub-source-token=t1_grow_conformance``); ``BETTERSTACK_STUB_QUERY_USER`` /
``BETTERSTACK_STUB_QUERY_PASSWORD`` (default ``stub-user`` / ``stub-password``);
``BETTERSTACK_STUB_HOST`` (``0.0.0.0``); ``BETTERSTACK_STUB_MAX_REQUEST_BYTES`` (10 MiB, measured
compressed); ``BETTERSTACK_STUB_MAX_RECORD_BYTES`` (10 MiB, uncompressed);
``BETTERSTACK_STUB_MAX_RECORDS`` (100000 kept, oldest dropped); ``BETTERSTACK_STUB_LOG`` (0).
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import re
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import msgpack_decode
import otlp
import sql

MIB = 1024 * 1024
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MAX_DRAIN_BYTES = 64 * MIB  # an oversized body is read and discarded up to this size before the 413
OTLP_PATHS = ("/v1/logs", "/v1/traces", "/v1/metrics")
DEFAULT_SOURCES = "stub-source-token=t1_grow_conformance"
MAX_DECOMPRESSED_FACTOR = 8  # a gzip body may inflate to at most 8 x the request limit
MAX_QUERY_BYTES = 256 * 1024
MAX_REQUEST_LOG = 500
INGEST_TYPES = ("application/json", "application/msgpack", "application/x-ndjson")
FAULT_BODIES = {
    402: "Quota exceeded",
    403: "Unauthorized",
    406: "Couldn't parse JSON content.",
    413: "payload reached size limit",
}
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ConfigError(ValueError):
    """Invalid stub configuration."""


class IngestError(Exception):
    def __init__(self, status: int, body: str, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(body)
        self.status = status
        self.body = body
        self.headers = dict(headers or {})


@dataclass(frozen=True)
class Config:
    host: str = "0.0.0.0"
    ingest_port: int = 8080
    query_port: int = 8123
    sources: Mapping[str, str] = field(default_factory=lambda: {"stub-source-token": "t1_grow_conformance"})
    query_user: str = "stub-user"
    query_password: str = "stub-password"
    max_request_bytes: int = 10 * MIB
    max_record_bytes: int = 10 * MIB
    max_records: int = 100_000
    log: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Config:
        def integer(name: str, default: int, minimum: int = 0, maximum: int = 2**31) -> int:
            raw = env.get(name, "").strip()
            if raw == "":
                return default
            if not raw.isdigit() or not minimum <= int(raw) <= maximum:
                raise ConfigError(f"{name} must be an integer between {minimum} and {maximum}")
            return int(raw)

        sources: dict[str, str] = {}
        for pair in (env.get("BETTERSTACK_STUB_SOURCES", "").strip() or DEFAULT_SOURCES).split(","):
            token, sep, table = pair.strip().partition("=")
            if not sep or not token or not _TABLE_RE.match(table):
                raise ConfigError("BETTERSTACK_STUB_SOURCES must be token=table pairs (table: [A-Za-z0-9_])")
            sources[token] = table
        log_flag = env.get("BETTERSTACK_STUB_LOG", "").strip().lower()
        return cls(
            host=env.get("BETTERSTACK_STUB_HOST", "").strip() or "0.0.0.0",
            ingest_port=integer("BETTERSTACK_STUB_INGEST_PORT", 8080, 0, 65535),
            query_port=integer("BETTERSTACK_STUB_QUERY_PORT", 8123, 0, 65535),
            sources=sources,
            query_user=env.get("BETTERSTACK_STUB_QUERY_USER", "") or "stub-user",
            query_password=env.get("BETTERSTACK_STUB_QUERY_PASSWORD", "") or "stub-password",
            max_request_bytes=integer("BETTERSTACK_STUB_MAX_REQUEST_BYTES", 10 * MIB, 1),
            max_record_bytes=integer("BETTERSTACK_STUB_MAX_RECORD_BYTES", 10 * MIB, 1),
            max_records=integer("BETTERSTACK_STUB_MAX_RECORDS", 100_000, 1),
            log=log_flag in ("1", "true", "yes", "on"),
        )


# --- event normalisation ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    """Convert MessagePack-only values (timestamps, bin) into JSON values."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64encode(value).decode("ascii")
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def event_time(dt: Any, received: datetime) -> datetime:
    """Better Stack ``dt`` rules: UNIX s/ms/ns (µs accepted too), RFC 3339 / ISO 8601 strings,
    MessagePack timestamps; anything unparseable falls back to the reception time."""
    if isinstance(dt, datetime):
        return dt.astimezone(UTC)
    if isinstance(dt, int) and not isinstance(dt, bool):
        # integer arithmetic: nanoseconds are truncated to microseconds, never rounded via float
        magnitude = abs(dt)
        try:
            if magnitude < 10**11:
                return EPOCH + timedelta(seconds=dt)
            if magnitude < 10**14:
                return EPOCH + timedelta(milliseconds=dt)
            if magnitude < 10**17:
                return EPOCH + timedelta(microseconds=dt)
            return EPOCH + timedelta(microseconds=dt // 1000)
        except OverflowError:
            return received
    if isinstance(dt, float):
        size = abs(dt)
        scale = 1.0 if size < 1e11 else 1e3 if size < 1e14 else 1e6 if size < 1e17 else 1e9
        try:
            return datetime.fromtimestamp(dt / scale, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return received
    if isinstance(dt, str):
        text = dt.strip()
        if re.fullmatch(r"-?\d+", text):
            return event_time(int(text), received)
        try:
            parsed = datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", text.replace("Z", "+00:00")))
        except ValueError:
            return received
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)
    return received


def decode_events(body: bytes, content_type: str) -> list[dict[str, Any]]:
    """Parse an ingest body into events or raise IngestError(406)."""
    bad = IngestError(406, FAULT_BODIES[406])
    try:
        if content_type == "application/msgpack":
            payload: Any = msgpack_decode.unpackb(body)
        elif content_type == "application/x-ndjson":
            payload = []
            for line in body.decode("utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    payload.extend(item if isinstance(item, list) else [item])
        else:
            payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise bad from exc
    events = payload if isinstance(payload, list) else [payload]
    if not all(isinstance(e, dict) for e in events):
        raise bad
    return events


# --- state ---------------------------------------------------------------------------------------------


@dataclass
class Record:
    table: str
    dt: datetime
    raw: str
    received: datetime


@dataclass
class Fault:
    status: int
    count: int
    target: str
    body: str
    headers: dict[str, str] = field(default_factory=dict)


class State:
    def __init__(self, max_records: int) -> None:
        self.lock = threading.Lock()
        self.records: deque[Record] = deque(maxlen=max_records)
        self.requests: deque[dict[str, Any]] = deque(maxlen=MAX_REQUEST_LOG)
        self.faults: list[Fault] = []

    def add(self, records: list[Record]) -> None:
        with self.lock:
            self.records.extend(records)

    def snapshot(self, table: str | None = None) -> list[Record]:
        with self.lock:
            return [r for r in self.records if table is None or r.table == table]

    def log_request(self, entry: dict[str, Any]) -> None:
        with self.lock:
            self.requests.append(entry)

    def take_fault(self, target: str) -> Fault | None:
        with self.lock:
            for index, fault in enumerate(self.faults):
                if fault.target == target:
                    fault.count -= 1
                    if fault.count == 0:
                        del self.faults[index]
                    return fault
            return None

    def reset(self) -> None:
        with self.lock:
            self.records.clear()
            self.requests.clear()
            self.faults.clear()


# --- HTTP ------------------------------------------------------------------------------------------------


class StubServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, config: Config, state: State, role: str, port: int) -> None:
        self.config = config
        self.state = state
        self.role = role
        super().__init__((config.host, port), StubHandler)


class StubHandler(BaseHTTPRequestHandler):
    server: StubServer
    server_version = "betterstack-stub/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        if self.server.config.log:
            sys.stderr.write(f"betterstack-stub[{self.server.role}]: {format % args}\n")

    def _send(self, status: int, body: bytes | str = b"", content_type: str = "text/plain; charset=utf-8",
              headers: Mapping[str, str] | None = None) -> None:  # fmt: skip
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        if data:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, status: int, doc: Any) -> None:
        self._send(status, json.dumps(doc, separators=(",", ":")), "application/json")

    def _read_body(self, limit: int) -> bytes:
        """Read Content-Length or chunked bodies; IngestError(413) past ``limit``, 411 without length."""
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            chunks: list[bytes] = []
            total = 0
            while True:
                line = self.rfile.readline(1024).strip()
                try:
                    size = int(line.split(b";")[0], 16)
                except ValueError as exc:
                    self.close_connection = True
                    raise IngestError(400, "invalid chunked encoding") from exc
                if size == 0:
                    while self.rfile.readline(1024).strip():
                        pass
                    return b"".join(chunks)
                total += size
                if total > limit:
                    self.close_connection = True
                    self._discard(size, MAX_DRAIN_BYTES)
                    self.rfile.readline(1024)
                    self._drain_chunks(MAX_DRAIN_BYTES - total)
                    raise IngestError(413, FAULT_BODIES[413])
                chunks.append(self.rfile.read(size))
                self.rfile.readline(1024)
        length = self.headers.get("Content-Length")
        if length is None:
            return b""
        if not length.isdigit():
            self.close_connection = True
            raise IngestError(400, "invalid Content-Length")
        if int(length) > limit:
            # Read (and drop) the body first so the client can finish writing and then read the
            # 413 instead of failing with EPIPE/ECONNRESET; bodies past MAX_DRAIN_BYTES are cut off.
            self.close_connection = True
            self._discard(int(length), MAX_DRAIN_BYTES)
            raise IngestError(413, FAULT_BODIES[413])
        return self.rfile.read(int(length))

    def _discard(self, size: int, cap: int) -> None:
        remaining = min(size, max(cap, 0))
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 64 * 1024))
            if not chunk:
                return
            remaining -= len(chunk)

    def _drain_chunks(self, cap: int) -> None:
        """Discard the rest of a chunked body (bounded by ``cap`` bytes)."""
        while cap > 0:
            line = self.rfile.readline(1024).strip()
            try:
                size = int(line.split(b";")[0], 16)
            except ValueError:
                return
            if size == 0:
                return
            self._discard(size, cap)
            cap -= size
            self.rfile.readline(1024)

    def _dispatch(self) -> None:
        parts = urlsplit(self.path)
        if parts.path.startswith("/__stub/"):
            self._control(parts.path, parse_qs(parts.query))
        elif self.server.role == "ingest":
            self._ingest(parts.path)
        else:
            self._query(parts.path, parse_qs(parts.query, keep_blank_values=True))

    do_GET = _dispatch
    do_POST = _dispatch
    do_PUT = _dispatch
    do_DELETE = _dispatch
    do_HEAD = _dispatch

    # --- ingest ------------------------------------------------------------------------------------

    def _ingest(self, path: str) -> None:
        cfg = self.server.config
        entry: dict[str, Any] = {
            "target": "ingest",
            "method": self.command,
            "path": path,
            "contentType": self.headers.get("Content-Type", ""),
            "contentEncoding": self.headers.get("Content-Encoding", ""),
            "bytes": 0,
            "records": 0,
            "time": time.time(),
        }
        try:
            status, payload, content_type = self._ingest_inner(path, cfg, entry)
            self._send(status, payload, content_type)
        except IngestError as exc:
            status = exc.status
            headers = {"Allow": "POST", **exc.headers} if exc.status == 405 else exc.headers
            self._send(exc.status, exc.body, headers=headers)
        entry["status"] = status
        self.server.state.log_request(entry)

    def _ingest_inner(self, path: str, cfg: Config, entry: dict[str, Any]) -> tuple[int, bytes, str]:
        if path != "/" and path not in OTLP_PATHS:
            self._read_body(cfg.max_request_bytes)
            raise IngestError(404, "Not Found")
        if self.command != "POST":
            raise IngestError(405, "Method Not Allowed")
        scheme, _, token = self.headers.get("Authorization", "").partition(" ")
        table = None
        if scheme.lower() == "bearer":
            for known, name in cfg.sources.items():
                if hmac.compare_digest(token.strip().encode(), known.encode()):
                    table = name
        body = self._read_body(cfg.max_request_bytes)
        entry["bytes"] = len(body)
        if table is None:
            raise IngestError(403, FAULT_BODIES[403])
        fault = self.server.state.take_fault("ingest")
        if fault is not None:
            raise IngestError(fault.status, fault.body, fault.headers)
        encoding = self.headers.get("Content-Encoding", "").strip().lower()
        if encoding == "gzip":
            body = self._gunzip(body, cfg.max_request_bytes * MAX_DECOMPRESSED_FACTOR)
        elif encoding not in ("", "identity"):
            raise IngestError(415, "Unsupported Content-Encoding")
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if path in OTLP_PATHS:
            return self._otlp(path, body, content_type, table, entry)
        if content_type not in INGEST_TYPES:
            raise IngestError(406, FAULT_BODIES[406])
        events = decode_events(body, content_type)
        received = datetime.now(tz=UTC)
        records: list[Record] = []
        for event in events:
            raw = json.dumps(_jsonable(event), separators=(",", ":"), ensure_ascii=False)
            if len(raw.encode()) > cfg.max_record_bytes:
                raise IngestError(413, FAULT_BODIES[413])
            records.append(Record(table, event_time(event.get("dt"), received), raw, received))
        self.server.state.add(records)
        entry["records"] = len(records)
        return 202, b"", ""

    def _otlp(
        self, path: str, body: bytes, content_type: str, table: str, entry: dict[str, Any]
    ) -> tuple[int, bytes, str]:
        """OTLP/HTTP on the ingesting host (/v1/logs, /v1/traces, /v1/metrics; protobuf or JSON).

        Logs are stored as records; traces and metrics are accepted and discarded."""
        if content_type not in ("application/x-protobuf", "application/json"):
            raise IngestError(415, "Unsupported Media Type")
        response = (
            (b"", "application/x-protobuf")
            if content_type == "application/x-protobuf"
            else (b"{}", "application/json")
        )
        entry["signal"] = path.rsplit("/", 1)[1]
        if path != "/v1/logs":
            return 200, *response
        try:
            if content_type == "application/x-protobuf":
                logs = otlp.decode_protobuf(body)
            else:
                logs = otlp.decode_json(json.loads(body.decode("utf-8")))
        except (otlp.OtlpError, ValueError, UnicodeDecodeError) as exc:
            raise IngestError(400, f"invalid OTLP logs payload: {exc}") from exc
        received = datetime.now(tz=UTC)
        records = []
        for log in logs:
            nanos = log["timeUnixNano"] or log["observedTimeUnixNano"]
            when = event_time(nanos, received) if nanos else received
            body_value = log["body"]
            event: dict[str, Any] = {
                "dt": when.isoformat().replace("+00:00", "Z"),
                "message": body_value if isinstance(body_value, str) else json.dumps(body_value),
                "level": log["severityText"],
                "severity_number": log["severityNumber"],
                "attributes": log["attributes"],
                "resource": log["resource"],
                "scope": log["scope"],
            }
            for key, name in (("traceId", "trace_id"), ("spanId", "span_id"), ("eventName", "event_name")):
                if log[key]:
                    event[name] = log[key]
            raw = json.dumps(_jsonable(event), separators=(",", ":"), ensure_ascii=False)
            if len(raw.encode()) > self.server.config.max_record_bytes:
                raise IngestError(413, FAULT_BODIES[413])
            records.append(Record(table, when, raw, received))
        self.server.state.add(records)
        entry["records"] = len(records)
        return 200, *response

    @staticmethod
    def _gunzip(body: bytes, limit: int) -> bytes:
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            out = inflater.decompress(body, limit + 1)
        except zlib.error as exc:
            raise IngestError(406, FAULT_BODIES[406]) from exc
        if len(out) > limit or inflater.unconsumed_tail:
            raise IngestError(413, FAULT_BODIES[413])
        if not inflater.eof:
            raise IngestError(406, FAULT_BODIES[406])
        return out

    # --- query --------------------------------------------------------------------------------------

    def _ch_error(self, status: int, code: tuple[int, str], message: str) -> None:
        number, name = code
        self._send(
            status,
            f"Code: {number}. DB::Exception: {message}. ({name}) (version stub)\n",
            headers={"X-ClickHouse-Exception-Code": str(number)},
        )

    def _authenticated(self, params: Mapping[str, list[str]]) -> bool:
        cfg = self.server.config
        user = password = None
        header = self.headers.get("Authorization", "")
        if header.lower().startswith("basic "):
            try:
                user, _, password = base64.b64decode(header[6:].strip()).decode("utf-8").partition(":")
            except (ValueError, UnicodeDecodeError):
                return False
        elif self.headers.get("X-ClickHouse-User") is not None:
            user, password = self.headers.get("X-ClickHouse-User"), self.headers.get("X-ClickHouse-Key", "")
        elif "user" in params:
            user, password = params["user"][0], params.get("password", [""])[0]
        if user is None or password is None:
            return False
        return hmac.compare_digest(user.encode(), cfg.query_user.encode()) and hmac.compare_digest(
            password.encode(), cfg.query_password.encode()
        )

    def _resolve(self, kind: str, table: str) -> tuple[list[str], list[dict[str, Any]]]:
        sources = set(self.server.config.sources.values())
        if kind == "remote":
            for suffix in ("_logs", "_spans", "_metrics"):
                base = table[: -len(suffix)]
                if table.endswith(suffix) and base in sources:
                    if suffix != "_logs":
                        return ["dt", "raw"], []
                    rows = [{"dt": r.dt, "raw": r.raw} for r in self.server.state.snapshot(base)]
                    return ["dt", "raw"], rows
        elif table.endswith("_s3") and table[:-3] in sources:
            return ["dt", "raw", "_row_type"], []
        raise sql.SqlError(sql.UNKNOWN_TABLE, f"Table {table} does not exist")

    def _query(self, path: str, params: Mapping[str, list[str]]) -> None:
        if path not in ("/", "/ping"):
            self._ch_error(404, sql.UNKNOWN_TABLE, f"There is no handle {path}")
            return
        if path == "/ping":
            self._send(200, "Ok.\n")
            return
        try:
            body = self._read_body(MAX_QUERY_BYTES) if self.command == "POST" else b""
        except IngestError as exc:
            self._ch_error(exc.status, sql.BAD_ARGUMENTS, exc.body)
            return
        if not self._authenticated(params):
            self._ch_error(
                401,
                (516, "AUTHENTICATION_FAILED"),
                "Authentication failed: password is incorrect, or there is no user with such name",
            )
            return
        fault = self.server.state.take_fault("query")
        if fault is not None:
            self._send(fault.status, fault.body, headers=fault.headers)
            return
        text = "\n".join(
            p for p in (params.get("query", [""])[0], body.decode("utf-8", "replace")) if p.strip()
        )
        self.server.state.log_request(
            {"target": "query", "method": self.command, "query": text, "time": time.time()}
        )
        if not text.strip():
            self._ch_error(400, sql.SYNTAX_ERROR, "Empty query")
            return
        try:
            bound = {k[6:]: v[0] for k, v in params.items() if k.startswith("param_")}
            query, names, rows = sql.execute(text, self._resolve, params=bound)
        except sql.SqlError as exc:
            status = {
                sql.UNKNOWN_TABLE[0]: 404,
                sql.UNKNOWN_IDENTIFIER[0]: 404,
                sql.UNKNOWN_FUNCTION[0]: 404,
                sql.UNKNOWN_FORMAT[0]: 404,
                sql.NOT_IMPLEMENTED[0]: 501,
            }.get(exc.code, 400)
            self._ch_error(status, (exc.code, exc.name), exc.message)
            return
        fmt = query.format or params.get("default_format", ["TabSeparated"])[0]
        fmt = sql.FORMATS.get(fmt.lower(), "")
        if not fmt:
            self._ch_error(404, sql.UNKNOWN_FORMAT, "Unknown output format")
            return
        settings = {
            k: v[0]
            for k, v in params.items()
            if k not in ("query", "user", "password", "default_format") and not k.startswith("param_")
        }
        settings.update(query.settings)
        content_type, payload = sql.render(fmt, names, rows, settings)
        summary = json.dumps({"read_rows": str(len(rows)), "result_rows": str(len(rows))})
        self._send(200, payload, content_type, {"X-ClickHouse-Format": fmt, "X-ClickHouse-Summary": summary})

    # --- controls -----------------------------------------------------------------------------------

    def _control(self, path: str, params: Mapping[str, list[str]]) -> None:
        state = self.server.state
        route = (self.command, path)
        if route == ("GET", "/__stub/health"):
            self._json(200, {"status": "ok", "role": self.server.role})
        elif route == ("GET", "/__stub/records"):
            table = params.get("table", [None])[0]
            records = [
                {
                    "table": r.table,
                    "dt": sql.format_datetime(r.dt),
                    "raw": r.raw,
                    "received": r.received.isoformat(),
                }
                for r in state.snapshot(table)
            ]
            self._json(200, {"records": records})
        elif route == ("DELETE", "/__stub/records"):
            with state.lock:
                state.records.clear()
            self._send(204)
        elif route == ("GET", "/__stub/requests"):
            with state.lock:
                self._json(200, {"requests": list(state.requests)})
        elif route == ("POST", "/__stub/fault"):
            self._add_fault()
        elif route == ("DELETE", "/__stub/fault"):
            with state.lock:
                state.faults.clear()
            self._send(204)
        elif route == ("POST", "/__stub/reset"):
            state.reset()
            self._send(204)
        else:
            self._json(404, {"error": "not_found"})

    def _add_fault(self) -> None:
        try:
            raw = json.loads(self._read_body(64 * 1024) or b"{}")
            if not isinstance(raw, dict):
                raise ValueError("fault must be an object")
            status = raw.get("status", 402)
            count = raw.get("count", 1)
            target = raw.get("target", "ingest")
            if not isinstance(status, int) or isinstance(status, bool) or not 100 <= status <= 599:
                raise ValueError("status must be an HTTP status code")
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                raise ValueError("count must be a positive integer")
            if target not in ("ingest", "query"):
                raise ValueError("target must be ingest or query")
            body = raw.get("body", FAULT_BODIES.get(status, "fault"))
            if not isinstance(body, str):
                raise ValueError("body must be a string")
            headers = raw.get("headers", {})
            if not isinstance(headers, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
            ):
                raise ValueError("headers must map strings to strings")
            retry_after = raw.get("retryAfter")
            if retry_after is not None:
                if isinstance(retry_after, bool) or not isinstance(retry_after, (int, str)):
                    raise ValueError("retryAfter must be a string or integer")
                headers = {**headers, "Retry-After": str(retry_after)}
        except (ValueError, IngestError) as exc:
            self._json(400, {"error": str(exc)})
            return
        with self.server.state.lock:
            self.server.state.faults.append(Fault(status, count, target, body, dict(headers)))
            queued = len(self.server.state.faults)
        self._json(200, {"queued": queued})


# --- entry point ---------------------------------------------------------------------------------------


class Stub:
    """Both listeners sharing one state."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.state = State(config.max_records)
        self.ingest = StubServer(config, self.state, "ingest", config.ingest_port)
        self.query = StubServer(config, self.state, "query", config.query_port)
        self._threads: list[threading.Thread] = []

    def start(self, poll_interval: float = 0.2) -> None:
        for srv in (self.ingest, self.query):
            thread = threading.Thread(
                target=srv.serve_forever, kwargs={"poll_interval": poll_interval}, daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        for srv in (self.ingest, self.query):
            srv.shutdown()
            srv.server_close()
        for thread in self._threads:
            thread.join(5)


def healthcheck(config: Config, timeout: float = 2.0) -> int:
    for port in (config.ingest_port, config.query_port):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/__stub/health", timeout=timeout
            ) as response:
                if response.status != 200:
                    return 1
        except (urllib.error.URLError, OSError):
            return 1
    return 0


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        config = Config.from_env(os.environ if env is None else env)
    except ConfigError as exc:
        sys.stderr.write(f"betterstack-stub: {exc}\n")
        return 2
    if args == ["--healthcheck"]:
        return healthcheck(config)
    if args:
        sys.stderr.write("usage: stub.py [--healthcheck]\n")
        return 2
    stub = Stub(config)
    done = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    signal.signal(signal.SIGINT, lambda *_: done.set())
    stub.start()
    sys.stderr.write(
        f"betterstack-stub: ingest on {config.host}:{stub.ingest.server_address[1]}, "
        f"query on {config.host}:{stub.query.server_address[1]}, sources {sorted(config.sources.values())}\n"
    )
    done.wait()
    stub.stop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
