#!/usr/bin/env python3
"""Grow Codes SDK demo service (Python standard library only).

The demo service is the backend for ``sdk-kit new demo`` and for the Docker
scenario ``core.health``. It serves exactly the paths of the skeleton client
every generated SDK starts with:

* ``GET /health``  -> ``200 {"status": "ok"}`` (no authentication)
* ``GET /v1/ping`` -> ``200 {"pong": true}`` with ``Authorization: Bearer <DEMO_TOKEN>``,
  otherwise ``401 {"error": "unauthorized"}``
* ``GET /version`` -> ``200 {"version": "<DEMO_VERSION>"}``

Every response carries an ``x-request-id`` header (``demo-<n>``).

Test controls (enabled unless ``DEMO_CONTROLS=0``) let integration tests make the
next responses fail, so retries, ``Retry-After`` handling and timeouts can be
exercised against a real container:

* ``POST /__fault`` with one fault object or a list of them; fields:
  ``status`` (int, default 503), ``count`` (int, default 1), ``path`` (only
  requests to this path; default every service path), ``method``,
  ``retryAfter`` (string sent as ``Retry-After``), ``delayMs`` (sleep before
  answering), ``body`` (JSON body; default ``{"error": "fault"}``),
  ``headers`` (extra response headers), ``reset`` (true = close the connection
  without an answer).
* ``GET /__fault`` lists the queued faults, ``DELETE /__fault`` clears them.
* ``GET /__requests`` lists the last requests (sensitive headers redacted),
  ``DELETE /__requests`` clears that list.
* ``GET /__stats`` returns request counts per path.
* ``POST /__reset`` clears faults, requests and counters.

Environment: ``DEMO_PORT`` (8080), ``DEMO_HOST`` (0.0.0.0), ``DEMO_TOKEN``
(``demo-token``), ``DEMO_VERSION`` (``1.0.0``), ``DEMO_CONTROLS`` (``1``),
``DEMO_LOG`` (``0``; ``1`` logs one line per request to stderr).

``python server.py --healthcheck`` exits 0 when ``/health`` on the local port
answers 200 (used by the container health check).
"""

from __future__ import annotations

import hmac
import json
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

SERVICE_PATHS = ("/health", "/v1/ping", "/version")
CONTROL_PREFIX = "/__"
MAX_CONTROL_BODY = 64 * 1024
MAX_REQUEST_LOG = 200
MAX_DELAY_MS = 120_000
REDACTED = "[REDACTED]"
SENSITIVE_HEADER_PARTS = (
    "authorization",
    "cookie",
    "token",
    "secret",
    "password",
    "key",
    "auth",
    "session",
    "signature",
    "credential",
)


class ConfigError(ValueError):
    """Invalid demo server configuration."""


@dataclass(frozen=True)
class Config:
    host: str = "0.0.0.0"
    port: int = 8080
    token: str = "demo-token"
    version: str = "1.0.0"
    controls: bool = True
    log: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Config:
        def flag(name: str, default: bool) -> bool:
            raw = env.get(name, "").strip().lower()
            if raw == "":
                return default
            if raw in ("1", "true", "yes", "on"):
                return True
            if raw in ("0", "false", "no", "off"):
                return False
            raise ConfigError(f"{name} must be a boolean")

        raw_port = env.get("DEMO_PORT", "").strip() or "8080"
        if not raw_port.isdigit() or not 0 <= int(raw_port) <= 65535:
            raise ConfigError("DEMO_PORT must be a port number")
        token = env.get("DEMO_TOKEN", "") or "demo-token"
        return cls(
            host=env.get("DEMO_HOST", "").strip() or "0.0.0.0",
            port=int(raw_port),
            token=token,
            version=env.get("DEMO_VERSION", "").strip() or "1.0.0",
            controls=flag("DEMO_CONTROLS", True),
            log=flag("DEMO_LOG", False),
        )


@dataclass
class Fault:
    status: int = 503
    count: int = 1
    path: str | None = None
    method: str | None = None
    retry_after: str | None = None
    delay_ms: int = 0
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    reset: bool = False

    @classmethod
    def parse(cls, raw: Any) -> Fault:
        if not isinstance(raw, dict):
            raise TypeError("fault must be an object")
        known = {"status", "count", "path", "method", "retryAfter", "delayMs", "body", "headers", "reset"}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(f"unknown fault field: {unknown[0]}")
        status = raw.get("status", 503)
        if not isinstance(status, int) or isinstance(status, bool) or not 100 <= status <= 599:
            raise ValueError("status must be an HTTP status code")
        count = raw.get("count", 1)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValueError("count must be a positive integer")
        path = raw.get("path")
        if path is not None and (not isinstance(path, str) or not path.startswith("/")):
            raise ValueError("path must start with /")
        method = raw.get("method")
        if method is not None and not isinstance(method, str):
            raise ValueError("method must be a string")
        retry_after = raw.get("retryAfter")
        if retry_after is not None:
            if isinstance(retry_after, bool) or not isinstance(retry_after, (str, int)):
                raise ValueError("retryAfter must be a string or integer")
            retry_after = str(retry_after)
        delay_ms = raw.get("delayMs", 0)
        if not isinstance(delay_ms, int) or isinstance(delay_ms, bool) or not 0 <= delay_ms <= MAX_DELAY_MS:
            raise ValueError(f"delayMs must be an integer between 0 and {MAX_DELAY_MS}")
        headers = raw.get("headers", {})
        if not isinstance(headers, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
        ):
            raise ValueError("headers must map strings to strings")
        reset = raw.get("reset", False)
        if not isinstance(reset, bool):
            raise TypeError("reset must be a boolean")
        return cls(
            status=status,
            count=count,
            path=path,
            method=method.upper() if method else None,
            retry_after=retry_after,
            delay_ms=delay_ms,
            body=raw.get("body"),
            headers=dict(headers),
            reset=reset,
        )

    def matches(self, method: str, path: str) -> bool:
        return (self.path is None or self.path == path) and (self.method is None or self.method == method)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status, "count": self.count}
        if self.path is not None:
            out["path"] = self.path
        if self.method is not None:
            out["method"] = self.method
        if self.retry_after is not None:
            out["retryAfter"] = self.retry_after
        if self.delay_ms:
            out["delayMs"] = self.delay_ms
        if self.body is not None:
            out["body"] = self.body
        if self.headers:
            out["headers"] = self.headers
        if self.reset:
            out["reset"] = True
        return out


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, value in headers.items():
        lower = name.lower()
        sensitive = any(part in lower for part in SENSITIVE_HEADER_PARTS)
        out[lower] = REDACTED if sensitive else value
    return out


class State:
    """Mutable server state shared by all request threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._faults: list[Fault] = []
        self._requests: deque[dict[str, Any]] = deque(maxlen=MAX_REQUEST_LOG)
        self._counts: dict[str, int] = {}
        self._next_id = 0

    def next_request_id(self) -> str:
        with self._lock:
            self._next_id += 1
            return f"demo-{self._next_id}"

    def add_faults(self, faults: list[Fault]) -> int:
        with self._lock:
            self._faults.extend(faults)
            return len(self._faults)

    def take_fault(self, method: str, path: str) -> Fault | None:
        with self._lock:
            for index, fault in enumerate(self._faults):
                if fault.matches(method, path):
                    fault.count -= 1
                    if fault.count == 0:
                        del self._faults[index]
                    return fault
            return None

    def faults(self) -> list[dict[str, Any]]:
        with self._lock:
            return [f.to_json() for f in self._faults]

    def clear_faults(self) -> None:
        with self._lock:
            self._faults.clear()

    def record(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._requests.append(entry)
            path = entry["path"]
            self._counts[path] = self._counts.get(path, 0) + 1

    def requests(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._requests)

    def clear_requests(self) -> None:
        with self._lock:
            self._requests.clear()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"total": sum(self._counts.values()), "paths": dict(self._counts)}

    def reset(self) -> None:
        with self._lock:
            self._faults.clear()
            self._requests.clear()
            self._counts.clear()


class DemoServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, config: Config) -> None:
        self.config = config
        self.state = State()
        super().__init__((config.host, config.port), DemoHandler)


class DemoHandler(BaseHTTPRequestHandler):
    server: DemoServer
    server_version = "grow-demo/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # --- plumbing -------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:
        if self.server.config.log:
            sys.stderr.write(f"demo: {self.address_string()} {format % args}\n")

    def _send(self, status: int, body: Any, headers: Mapping[str, str] | None = None) -> None:
        payload = b"" if body is None else json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("x-request-id", self._request_id)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        if status not in (204, 304):
            self.send_header("Content-Length", str(len(payload)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if length is None:
            return b""
        if not length.isdigit():
            raise ValueError("invalid Content-Length")
        size = int(length)
        if size > MAX_CONTROL_BODY:
            raise OverflowError("body too large")
        return self.rfile.read(size)

    def _drain(self) -> bool:
        """Discard a request body on service paths so keep-alive stays in sync."""
        try:
            self._read_body()
        except OverflowError:
            self.close_connection = True
            self._send(413, {"error": "body too large"})
            return False
        except ValueError:
            self.close_connection = True
            self._send(400, {"error": "invalid Content-Length"})
            return False
        return True

    def _dispatch(self) -> None:
        self._request_id = self.server.state.next_request_id()
        path = urlsplit(self.path).path
        if path.startswith(CONTROL_PREFIX):
            if self.server.config.controls:
                self._control(path)
            else:
                self._send(404, {"error": "not_found"})
            return
        if not self._drain():
            return
        self.server.state.record(
            {
                "method": self.command,
                "path": path,
                "query": urlsplit(self.path).query,
                "headers": redact_headers(dict(self.headers.items())),
                "requestId": self._request_id,
                "time": time.time(),
            }
        )
        fault = self.server.state.take_fault(self.command, path)
        if fault is not None:
            self._apply_fault(fault)
            return
        self._service(path)

    do_GET = _dispatch
    do_POST = _dispatch
    do_PUT = _dispatch
    do_DELETE = _dispatch
    do_PATCH = _dispatch
    do_HEAD = _dispatch

    # --- service paths --------------------------------------------------

    def _service(self, path: str) -> None:
        if path not in SERVICE_PATHS:
            self._send(404, {"error": "not_found"})
            return
        if self.command not in ("GET", "HEAD"):
            self._send(405, {"error": "method_not_allowed"}, {"Allow": "GET, HEAD"})
            return
        if path == "/health":
            self._send(200, {"status": "ok"})
        elif path == "/version":
            self._send(200, {"version": self.server.config.version})
        elif self._authorized():
            self._send(200, {"pong": True})
        else:
            self._send(401, {"error": "unauthorized"}, {"WWW-Authenticate": 'Bearer realm="demo"'})

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        scheme, _, credential = header.partition(" ")
        if scheme.lower() != "bearer" or not credential:
            return False
        return hmac.compare_digest(credential.strip().encode(), self.server.config.token.encode())

    def _apply_fault(self, fault: Fault) -> None:
        if fault.delay_ms:
            time.sleep(fault.delay_ms / 1000)
        if fault.reset:
            self.close_connection = True
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        headers = dict(fault.headers)
        if fault.retry_after is not None:
            headers["Retry-After"] = fault.retry_after
        body = fault.body if fault.body is not None else {"error": "fault"}
        self._send(fault.status, body, headers)

    # --- test controls --------------------------------------------------

    def _control(self, path: str) -> None:
        state = self.server.state
        route = (self.command, path)
        if route == ("POST", "/__fault"):
            try:
                raw = json.loads(self._read_body() or b"{}")
                items = raw if isinstance(raw, list) else [raw]
                faults = [Fault.parse(item) for item in items]
            except OverflowError:
                self._send(413, {"error": "body too large"})
                return
            except (ValueError, TypeError) as exc:
                self._send(400, {"error": str(exc)})
                return
            self._send(200, {"queued": state.add_faults(faults)})
        elif route == ("GET", "/__fault"):
            self._send(200, {"faults": state.faults()})
        elif route == ("DELETE", "/__fault"):
            state.clear_faults()
            self._send(204, None)
        elif route == ("GET", "/__requests"):
            self._send(200, {"requests": state.requests()})
        elif route == ("DELETE", "/__requests"):
            state.clear_requests()
            self._send(204, None)
        elif route == ("GET", "/__stats"):
            self._send(200, state.stats())
        elif route == ("POST", "/__reset"):
            state.reset()
            self._send(204, None)
        else:
            self._send(404, {"error": "not_found"})


def healthcheck(port: int, timeout: float = 2.0) -> int:
    """Return 0 when the local /health answers 200, else 1."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as response:
            return 0 if response.status == 200 else 1
    except (urllib.error.URLError, OSError):
        return 1


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        config = Config.from_env(os.environ if env is None else env)
    except ConfigError as exc:
        sys.stderr.write(f"demo: {exc}\n")
        return 2
    if args == ["--healthcheck"]:
        return healthcheck(config.port)
    if args:
        sys.stderr.write("usage: server.py [--healthcheck]\n")
        return 2
    server = DemoServer(config)

    def stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    sys.stderr.write(f"demo: listening on {config.host}:{server.server_address[1]}\n")
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
