"""Tests for fakeintake.py against a local server that mimics the fakeintake API surface
(server.go: POST any path, /fakeintake/payloads, /routestats, /flushPayloads, /configure/override,
/debug/lastAPIKey/, /fakeintake/health)."""

from __future__ import annotations

import base64
import gzip
import json
import sys
import threading
import urllib.request
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fakeintake as fi


class Fake(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.store: dict[str, list[dict[str, Any]]] = {}
        self.overrides: list[dict[str, Any]] = []
        self.last_key = ""
        self.healthy = True


class Handler(BaseHTTPRequestHandler):
    server: Fake

    def log_message(self, *args: Any) -> None:
        pass

    def reply(self, status: int, body: bytes = b"", ctype: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        if parts.path == "/fakeintake/health":
            self.reply(200 if self.server.healthy else 500)
        elif parts.path == "/fakeintake/payloads":
            endpoint = parse_qs(parts.query).get("endpoint", [""])[0]
            self.reply(200, json.dumps({"payloads": self.server.store.get(endpoint, [])}).encode())
        elif parts.path == "/fakeintake/routestats":
            stats = {k: {"id": k, "count": len(v)} for k, v in self.server.store.items()}
            self.reply(200, json.dumps({"routes": stats}).encode())
        elif parts.path == "/fakeintake/flushPayloads":
            self.server.store.clear()
            self.reply(200)
        elif parts.path == "/debug/lastAPIKey/":
            self.reply(200, self.server.last_key.encode(), "text/plain")
        else:
            self.reply(404)

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/fakeintake/configure/override":
            self.server.overrides.append(json.loads(body))
            self.reply(200)
            return
        key = self.headers.get("DD-API-KEY", "")
        self.server.last_key = key
        encoding = self.headers.get("Content-Encoding") or self.headers.get("Content-Type", "")
        self.server.store.setdefault(self.path, []).append(
            {
                "timestamp": datetime.now(tz=UTC).isoformat(),
                "api_key": key,
                "data": base64.b64encode(body).decode(),
                "encoding": encoding,
                "content_type": self.headers.get("Content-Type", ""),
            }
        )
        self.reply(200, b'{"errors":[]}')


@pytest.fixture()
def fake() -> Iterator[Fake]:
    srv = Fake()
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def url(srv: Fake) -> str:
    return f"http://127.0.0.1:{srv.server_address[1]}"


def post(srv: Fake, path: str, body: bytes, encoding: str = "", ctype: str = "application/json") -> None:
    req = urllib.request.Request(url(srv) + path, data=body, method="POST")
    req.add_header("Content-Type", ctype)
    req.add_header("DD-API-KEY", "abcdefgh12345678")
    if encoding:
        req.add_header("Content-Encoding", encoding)
    urllib.request.urlopen(req, timeout=5).read()


def test_logs_with_all_encodings(fake: Fake) -> None:
    post(
        fake,
        "/api/v2/logs",
        json.dumps([{"message": "plain r1", "service": "svc", "attr": {"run": "r1"}}]).encode(),
    )
    post(
        fake,
        "/api/v2/logs",
        gzip.compress(json.dumps([{"message": "zipped r1", "service": "other"}]).encode()),
        "gzip",
    )
    post(fake, "/api/v2/logs", zlib.compress(json.dumps({"message": "deflated r2"}).encode()), "deflate")
    base = url(fake)
    records = fi.logs(base)
    assert [r["message"] for r in records] == ["plain r1", "zipped r1", "deflated r2"]
    assert records[0]["attr"] == {"run": "r1"}  # custom attributes survive
    assert [r["message"] for r in fi.logs(base, contains="r1")] == ["plain r1", "zipped r1"]
    assert [r["message"] for r in fi.logs(base, service="svc")] == ["plain r1"]
    assert fi.routes(base) == {"/api/v2/logs": 3}


def test_payloads_binary_bad_encoding_and_masking(fake: Fake) -> None:
    post(fake, "/api/v0.2/traces", gzip.compress(b"\x00\x01protobuf"), "gzip", "application/x-protobuf")
    post(fake, "/api/v0.2/traces", b"not gzip", "gzip")
    post(fake, "/api/v0.2/traces", b"", "", "application/json")
    base = url(fake)
    items = fi.payloads(base, "/api/v0.2/traces")
    assert items[0]["binary"] is True and base64.b64decode(items[0]["data"]) == b"\x00\x01protobuf"
    assert items[0]["apiKey"] == "abcd…"
    assert "cannot inflate" in items[1]["error"]
    assert items[2]["data"] is None
    assert fi.payloads(base, "/api/v0.2/traces", reveal=True)[0]["apiKey"] == "abcdefgh12345678"
    assert fi.payloads(base, "/nothing") == []
    assert fi.mask("") == "" and fi.mask("short") == "…"


def test_zstd_payload() -> None:
    try:
        from compression import zstd  # noqa: PLC0415 - Python >= 3.14
    except ImportError:
        with pytest.raises(fi.FakeintakeError, match="zstd"):
            fi.inflate(b"x", "zstd")
        return
    assert fi.inflate(zstd.compress(b'{"a":1}'), "zstd") == b'{"a":1}'


def test_wait_override_flush_last_key(fake: Fake) -> None:
    base = url(fake)

    def later() -> None:
        post(fake, "/api/v2/logs", json.dumps([{"message": "late x1"}]).encode())

    timer = threading.Timer(0.3, later)
    timer.start()
    assert fi.wait(base, "/api/v2/logs", contains="x1", timeout=5, interval=0.05) == 1
    assert fi.wait(base, "/api/v2/logs", minimum=1, timeout=1) == 1
    with pytest.raises(TimeoutError):
        fi.wait(base, "/api/v2/series", timeout=0.2, interval=0.05)
    fi.override(base, "/api/v2/logs", 202)
    assert fake.overrides == [
        {"endpoint": "/api/v2/logs", "method": "POST", "status_code": 202, "content_type": "application/json",
         "body": "e30="}
    ]  # fmt: skip
    assert fi.last_api_key(base) == "abcd…"
    assert fi.last_api_key(base, reveal=True) == "abcdefgh12345678"
    fi.flush(base)
    assert fi.routes(base) == {}


def test_health_and_errors(fake: Fake) -> None:
    base = url(fake)
    assert fi.health(base)
    fake.healthy = False
    assert not fi.health(base)
    with pytest.raises(fi.FakeintakeError, match="HTTP 404"):
        fi._request(base, "/missing")
    assert not fi.health("http://127.0.0.1:1")
    with pytest.raises(TimeoutError):
        fi.wait("http://127.0.0.1:1", "/api/v2/logs", timeout=0.1, interval=0.05)


def test_cli(fake: Fake, capsys: pytest.CaptureFixture[str]) -> None:
    base = url(fake)
    post(fake, "/api/v2/logs", json.dumps([{"message": "cli r9", "service": "s"}]).encode())
    assert fi.main(["--url", base, "health"]) == 0
    assert fi.main(["--url", base, "routes"]) == 0
    assert json.loads(capsys.readouterr().out) == {"/api/v2/logs": 1}
    assert fi.main(["--url", base, "logs", "--contains", "r9", "--service", "s"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["message"] == "cli r9"
    assert fi.main(["--url", base, "payloads", "/api/v2/logs"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["apiKey"] == "abcd…"
    assert fi.main(["--url", base, "wait", "/api/v2/logs", "--min", "1", "--timeout", "1"]) == 0
    assert json.loads(capsys.readouterr().out) == {"endpoint": "/api/v2/logs", "count": 1}
    assert fi.main(["--url", base, "override", "/api/v2/logs", "202", "--body", "{}"]) == 0
    assert fi.main(["--url", base, "last-api-key"]) == 0
    assert capsys.readouterr().out.strip() == "abcd…"
    assert fi.main(["--url", base, "flush"]) == 0
    assert fi.main(["--url", base, "wait", "/api/v2/logs", "--timeout", "0.1"]) == 1
    assert "fakeintake:" in capsys.readouterr().err
    fake.healthy = False
    assert fi.main(["--url", base, "health"]) == 1
