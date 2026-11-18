#!/usr/bin/env python3
"""Query a Datadog fakeintake (``datadog/fakeintake``) — Python standard library only.

Usable as a module or a CLI. The base URL comes from ``--url`` or ``FAKEINTAKE_URL``
(default ``http://127.0.0.1:80``).

    fakeintake.py health                         exit 0 when /fakeintake/health answers 200
    fakeintake.py routes                         {"<path>": count} of received payloads
    fakeintake.py payloads /api/v2/logs          decoded raw payloads of one route (JSON)
    fakeintake.py logs [--contains TEXT] [--service NAME]
                                                 every log record received on /api/v2/logs, all fields
    fakeintake.py wait /api/v2/logs [--min N] [--contains TEXT] [--timeout S]
                                                 wait until a route has N payloads (or N matching logs)
    fakeintake.py override /api/v2/logs 202 [--body '{}'] [--method POST]
                                                 fixed response for a route
    fakeintake.py flush                          drop every stored payload
    fakeintake.py last-api-key [--reveal]        the API key of the last request (masked by default)

fakeintake stores the raw body of every POST with its Content-Encoding (or Content-Type when no
encoding was sent); ``GET /fakeintake/payloads?endpoint=<path>`` returns them base64-encoded. This
helper inflates gzip and deflate bodies (and zstd when the Python runtime has ``compression.zstd``)
and parses JSON, so log attributes that fakeintake's own ``format=json`` parser drops stay visible.
API keys are masked in all output unless ``--reveal`` is given.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any

DEFAULT_URL = "http://127.0.0.1:80"
LOGS_ROUTE = "/api/v2/logs"


class FakeintakeError(RuntimeError):
    """fakeintake answered with an error or could not be reached."""


def _request(
    base: str, path: str, data: bytes | None = None, method: str | None = None, timeout: float = 10
) -> bytes:
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return bytes(response.read())
    except urllib.error.HTTPError as exc:
        raise FakeintakeError(f"{method or 'GET'} {path}: HTTP {exc.code}") from exc
    except OSError as exc:
        raise FakeintakeError(f"{method or 'GET'} {path}: {exc}") from exc


def mask(key: str | None) -> str:
    if not key:
        return ""
    return key[:4] + "…" if len(key) > 8 else "…"


def inflate(data: bytes, encoding: str) -> bytes:
    enc = (encoding or "").lower()
    if enc == "gzip":
        return gzip.decompress(data)
    if enc == "deflate":
        return zlib.decompress(data)
    if enc == "zstd":
        try:
            from compression import zstd  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415 - Python >= 3.14
        except ImportError as exc:
            raise FakeintakeError("zstd payload: this Python has no compression.zstd (needs 3.14+)") from exc
        return bytes(zstd.decompress(data))
    return data


def health(base: str) -> bool:
    try:
        _request(base, "/fakeintake/health", timeout=3)
    except FakeintakeError:
        return False
    return True


def routes(base: str) -> dict[str, int]:
    doc = json.loads(_request(base, "/fakeintake/routestats") or b"{}")
    return {route: int(stat.get("count", 0)) for route, stat in (doc.get("routes") or {}).items()}


def payloads(base: str, endpoint: str, reveal: bool = False) -> list[dict[str, Any]]:
    """Raw payloads of one route, decoded: ``data`` is parsed JSON when possible, else base64."""
    query = urllib.parse.urlencode({"endpoint": endpoint})
    doc = json.loads(_request(base, f"/fakeintake/payloads?{query}") or b"{}")
    out: list[dict[str, Any]] = []
    for item in doc.get("payloads") or []:
        raw = base64.b64decode(item.get("data") or "")
        entry: dict[str, Any] = {
            "timestamp": item.get("timestamp"),
            "apiKey": item.get("api_key") if reveal else mask(item.get("api_key")),
            "encoding": item.get("encoding", ""),
            "contentType": item.get("content_type", ""),
        }
        try:
            body = inflate(raw, entry["encoding"])
        except (OSError, zlib.error, EOFError) as exc:
            entry["error"] = f"cannot inflate: {exc}"
            entry["data"] = base64.b64encode(raw).decode()
            out.append(entry)
            continue
        try:
            entry["data"] = json.loads(body) if body.strip() else None
        except (ValueError, UnicodeDecodeError):
            entry["data"] = base64.b64encode(body).decode()
            entry["binary"] = True
        out.append(entry)
    return out


def logs(base: str, contains: str | None = None, service: str | None = None) -> list[dict[str, Any]]:
    """Every log record received on /api/v2/logs (a JSON array per request), optionally filtered."""
    records: list[dict[str, Any]] = []
    for entry in payloads(base, LOGS_ROUTE):
        data = entry.get("data")
        items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        records.extend(item for item in items if isinstance(item, dict))
    if contains is not None:
        records = [r for r in records if contains in json.dumps(r, ensure_ascii=False)]
    if service is not None:
        records = [r for r in records if r.get("service") == service]
    return records


def wait(
    base: str,
    endpoint: str,
    minimum: int = 1,
    *,
    contains: str | None = None,
    timeout: float = 30,
    interval: float = 0.5,
) -> int:
    """Wait until ``endpoint`` has ``minimum`` payloads (for /api/v2/logs with ``contains``:
    matching log records). Returns the count; raises TimeoutError."""
    deadline = time.monotonic() + timeout
    count = 0
    while True:
        try:
            if endpoint == LOGS_ROUTE and contains is not None:
                count = len(logs(base, contains=contains))
            else:
                count = routes(base).get(endpoint, 0)
        except FakeintakeError:
            count = 0
        if count >= minimum:
            return count
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{endpoint}: {count} < {minimum} after {timeout}s")
        time.sleep(interval)


def override(base: str, endpoint: str, status: int, body: str = "{}", method: str = "POST") -> None:
    payload = {
        "endpoint": endpoint,
        "method": method,
        "status_code": status,
        "content_type": "application/json",
        "body": base64.b64encode(body.encode()).decode(),  # Go []byte -> base64 in JSON
    }
    _request(base, "/fakeintake/configure/override", json.dumps(payload).encode(), "POST")


def flush(base: str) -> None:
    _request(base, "/fakeintake/flushPayloads", method="GET")


def last_api_key(base: str, reveal: bool = False) -> str:
    key = _request(base, "/debug/lastAPIKey/").decode().strip()
    return key if reveal else mask(key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fakeintake.py", description="Query a Datadog fakeintake.")
    parser.add_argument("--url", default=os.environ.get("FAKEINTAKE_URL", DEFAULT_URL))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health")
    sub.add_parser("routes")
    p = sub.add_parser("payloads")
    p.add_argument("endpoint")
    p.add_argument("--reveal", action="store_true")
    p = sub.add_parser("logs")
    p.add_argument("--contains")
    p.add_argument("--service")
    p = sub.add_parser("wait")
    p.add_argument("endpoint")
    p.add_argument("--min", type=int, default=1)
    p.add_argument("--contains")
    p.add_argument("--timeout", type=float, default=30)
    p = sub.add_parser("override")
    p.add_argument("endpoint")
    p.add_argument("status", type=int)
    p.add_argument("--body", default="{}")
    p.add_argument("--method", default="POST")
    sub.add_parser("flush")
    p = sub.add_parser("last-api-key")
    p.add_argument("--reveal", action="store_true")
    args = parser.parse_args(argv)

    def show(value: Any) -> None:
        sys.stdout.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")

    try:
        if args.command == "health":
            return 0 if health(args.url) else 1
        if args.command == "routes":
            show(routes(args.url))
        elif args.command == "payloads":
            show(payloads(args.url, args.endpoint, reveal=args.reveal))
        elif args.command == "logs":
            show(logs(args.url, contains=args.contains, service=args.service))
        elif args.command == "wait":
            show(
                {
                    "endpoint": args.endpoint,
                    "count": wait(
                        args.url, args.endpoint, args.min, contains=args.contains, timeout=args.timeout
                    ),
                }
            )
        elif args.command == "override":
            override(args.url, args.endpoint, args.status, args.body, args.method)
        elif args.command == "flush":
            flush(args.url)
        else:
            sys.stdout.write(last_api_key(args.url, reveal=args.reveal) + "\n")
    except (FakeintakeError, TimeoutError) as exc:
        sys.stderr.write(f"fakeintake: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
