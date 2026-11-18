"""Unit tests for the demo service (run: pytest demo/tests --cov=server)."""

from __future__ import annotations

import http.client
import json
import signal
import socket
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server

TOKEN = "unit-token-1234"


@pytest.fixture()
def demo() -> Iterator[server.DemoServer]:
    srv = server.DemoServer(server.Config(host="127.0.0.1", port=0, token=TOKEN))
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def call(
    srv: server.DemoServer,
    method: str,
    path: str,
    body: Any = None,
    *,
    headers: dict[str, str] | None = None,
    raw: bytes | None = None,
) -> tuple[int, dict[str, str], Any]:
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    conn.request(method, path, body=data, headers=headers or {})
    resp = conn.getresponse()
    payload = resp.read()
    conn.close()
    parsed = json.loads(payload) if payload else None
    return resp.status, {k.lower(): v for k, v in resp.getheaders()}, parsed


# --- service paths ---------------------------------------------------------


def test_health(demo: server.DemoServer) -> None:
    status, headers, body = call(demo, "GET", "/health")
    assert status == 200
    assert body == {"status": "ok"}
    assert headers["content-type"] == "application/json"
    assert headers["x-request-id"].startswith("demo-")


def test_version(demo: server.DemoServer) -> None:
    assert call(demo, "GET", "/version")[2] == {"version": "1.0.0"}


def test_ping_requires_bearer_token(demo: server.DemoServer) -> None:
    ok = call(demo, "GET", "/v1/ping", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok[0] == 200 and ok[2] == {"pong": True}
    lower = call(demo, "GET", "/v1/ping", headers={"Authorization": f"bearer {TOKEN}"})
    assert lower[0] == 200
    for header in (
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": "Bearer"},
    ):
        status, headers, body = call(demo, "GET", "/v1/ping", headers=header)
        assert status == 401
        assert body == {"error": "unauthorized"}
        assert "bearer" in headers["www-authenticate"].lower()


def test_unknown_path_and_method(demo: server.DemoServer) -> None:
    status, _, body = call(demo, "GET", "/nope")
    assert (status, body) == (404, {"error": "not_found"})
    status, headers, body = call(demo, "POST", "/health", body={"x": 1})
    assert (status, body) == (405, {"error": "method_not_allowed"})
    assert headers["allow"] == "GET, HEAD"


def test_head_has_no_body(demo: server.DemoServer) -> None:
    status, headers, body = call(demo, "HEAD", "/health")
    assert status == 200 and body is None
    assert headers["content-length"] == "15"


def test_keep_alive_after_body_on_service_path(demo: server.DemoServer) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", demo.server_address[1], timeout=5)
    conn.request("POST", "/version", body=b'{"ignored":true}', headers={"Content-Type": "application/json"})
    first = conn.getresponse()
    first.read()
    conn.request("GET", "/version")
    second = conn.getresponse()
    assert (first.status, second.status) == (405, 200)
    assert json.loads(second.read()) == {"version": "1.0.0"}
    conn.close()


def test_body_too_large_and_bad_length(demo: server.DemoServer) -> None:
    status, _, body = call(
        demo, "POST", "/health", headers={"Content-Length": str(server.MAX_CONTROL_BODY + 1)}, raw=b""
    )
    assert (status, body) == (413, {"error": "body too large"})
    sock = socket.create_connection(("127.0.0.1", demo.server_address[1]), timeout=5)
    sock.sendall(b"POST /health HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n")
    data = sock.recv(4096)
    sock.close()
    assert data.startswith(b"HTTP/1.1 400")


def test_request_ids_increase(demo: server.DemoServer) -> None:
    first = call(demo, "GET", "/health")[1]["x-request-id"]
    second = call(demo, "GET", "/health")[1]["x-request-id"]
    assert int(second.split("-")[1]) == int(first.split("-")[1]) + 1


# --- faults ----------------------------------------------------------------


def test_fault_503_then_success(demo: server.DemoServer) -> None:
    status, _, body = call(demo, "POST", "/__fault", body={"status": 503, "count": 2, "path": "/health"})
    assert (status, body) == (200, {"queued": 1})
    assert call(demo, "GET", "/version")[0] == 200  # other path untouched
    assert call(demo, "GET", "/health")[0] == 503
    status, _, body = call(demo, "GET", "/health")
    assert (status, body) == (503, {"error": "fault"})
    assert call(demo, "GET", "/health")[0] == 200


def test_fault_429_retry_after_custom_body_headers(demo: server.DemoServer) -> None:
    call(
        demo,
        "POST",
        "/__fault",
        body=[
            {"status": 429, "retryAfter": 1, "body": {"error": "slow down"}, "headers": {"x-extra": "1"}},
            {"status": 500, "method": "post"},
        ],
    )
    faults = call(demo, "GET", "/__fault")[2]["faults"]
    assert faults == [
        {
            "status": 429,
            "count": 1,
            "retryAfter": "1",
            "body": {"error": "slow down"},
            "headers": {"x-extra": "1"},
        },
        {"status": 500, "count": 1, "method": "POST"},
    ]
    status, headers, body = call(demo, "GET", "/v1/ping")
    assert (status, body) == (429, {"error": "slow down"})
    assert headers["retry-after"] == "1"
    assert headers["x-extra"] == "1"
    # the POST-only fault does not match GET
    assert call(demo, "GET", "/health")[0] == 200
    assert call(demo, "POST", "/version")[0] == 500
    assert call(demo, "GET", "/__fault")[2] == {"faults": []}


def test_fault_delay_and_reset(demo: server.DemoServer) -> None:
    call(demo, "POST", "/__fault", body={"delayMs": 200, "status": 504, "path": "/version", "reset": False})
    started = time.monotonic()
    assert call(demo, "GET", "/version")[0] == 504
    assert time.monotonic() - started >= 0.19
    call(demo, "POST", "/__fault", body={"reset": True, "path": "/health"})
    conn = http.client.HTTPConnection("127.0.0.1", demo.server_address[1], timeout=5)
    conn.request("GET", "/health")
    with pytest.raises((http.client.RemoteDisconnected, ConnectionError)):
        conn.getresponse()
    conn.close()
    assert call(demo, "GET", "/health")[0] == 200


def test_fault_listing_includes_all_fields(demo: server.DemoServer) -> None:
    call(demo, "POST", "/__fault", body={"delayMs": 5, "reset": True, "path": "/x"})
    assert call(demo, "GET", "/__fault")[2]["faults"] == [
        {"status": 503, "count": 1, "path": "/x", "delayMs": 5, "reset": True}
    ]
    assert call(demo, "DELETE", "/__fault")[0] == 204
    assert call(demo, "GET", "/__fault")[2] == {"faults": []}


@pytest.mark.parametrize(
    "fault,message",
    [
        ("x", "fault must be an object"),
        ({"bogus": 1}, "unknown fault field: bogus"),
        ({"status": 99}, "status must be an HTTP status code"),
        ({"status": True}, "status must be an HTTP status code"),
        ({"count": 0}, "count must be a positive integer"),
        ({"path": "health"}, "path must start with /"),
        ({"method": 1}, "method must be a string"),
        ({"retryAfter": True}, "retryAfter must be a string or integer"),
        ({"delayMs": -1}, "delayMs must be an integer between 0 and 120000"),
        ({"headers": {"a": 1}}, "headers must map strings to strings"),
        ({"reset": "yes"}, "reset must be a boolean"),
    ],
)
def test_fault_validation(demo: server.DemoServer, fault: Any, message: str) -> None:
    status, _, body = call(demo, "POST", "/__fault", body=fault)
    assert (status, body) == (400, {"error": message})


def test_fault_bad_json_and_large_body(demo: server.DemoServer) -> None:
    assert call(demo, "POST", "/__fault", raw=b"{not json")[0] == 400
    big = b"[" + b"{}," * (server.MAX_CONTROL_BODY // 3) + b"{}]"
    assert call(demo, "POST", "/__fault", raw=big)[0] == 413
    # empty body = one default fault
    assert call(demo, "POST", "/__fault", raw=b"")[2] == {"queued": 1}


# --- requests, stats, reset --------------------------------------------------


def test_requests_are_recorded_with_redaction(demo: server.DemoServer) -> None:
    call(
        demo,
        "GET",
        "/v1/ping?x=1",
        headers={"Authorization": f"Bearer {TOKEN}", "X-Api-Key": "k", "User-Agent": "ua/1"},
    )
    entries = call(demo, "GET", "/__requests")[2]["requests"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["method"] == "GET" and entry["path"] == "/v1/ping" and entry["query"] == "x=1"
    assert entry["headers"]["authorization"] == "[REDACTED]"
    assert entry["headers"]["x-api-key"] == "[REDACTED]"
    assert entry["headers"]["user-agent"] == "ua/1"
    assert TOKEN not in json.dumps(entries)
    assert call(demo, "DELETE", "/__requests")[0] == 204
    assert call(demo, "GET", "/__requests")[2] == {"requests": []}


def test_stats_and_reset(demo: server.DemoServer) -> None:
    call(demo, "GET", "/health")
    call(demo, "GET", "/health")
    call(demo, "GET", "/version")
    call(demo, "POST", "/__fault", body={})
    assert call(demo, "GET", "/__stats")[2] == {"total": 3, "paths": {"/health": 2, "/version": 1}}
    assert call(demo, "POST", "/__reset")[0] == 204
    assert call(demo, "GET", "/__stats")[2] == {"total": 0, "paths": {}}
    assert call(demo, "GET", "/__fault")[2] == {"faults": []}
    assert call(demo, "GET", "/__requests")[2] == {"requests": []}


def test_unknown_control(demo: server.DemoServer) -> None:
    assert call(demo, "GET", "/__nope")[0] == 404
    assert call(demo, "PUT", "/__fault")[0] == 404


def test_controls_disabled() -> None:
    srv = server.DemoServer(server.Config(host="127.0.0.1", port=0, controls=False, log=True))
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        assert call(srv, "POST", "/__fault", body={})[0] == 404
        assert call(srv, "GET", "/v1/ping", headers={"Authorization": "Bearer demo-token"})[0] == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_request_log_is_bounded() -> None:
    state = server.State()
    for i in range(server.MAX_REQUEST_LOG + 5):
        state.record({"path": f"/p{i % 2}"})
    assert len(state.requests()) == server.MAX_REQUEST_LOG
    assert state.stats()["total"] == server.MAX_REQUEST_LOG + 5


# --- config, healthcheck, main ---------------------------------------------------


def test_config_from_env_defaults_and_values() -> None:
    assert server.Config.from_env({}) == server.Config()
    cfg = server.Config.from_env(
        {
            "DEMO_PORT": "9000",
            "DEMO_HOST": "127.0.0.1",
            "DEMO_TOKEN": "t",
            "DEMO_VERSION": "2.0.0",
            "DEMO_CONTROLS": "off",
            "DEMO_LOG": "YES",
        }
    )
    assert cfg == server.Config("127.0.0.1", 9000, "t", "2.0.0", False, True)


@pytest.mark.parametrize("env", [{"DEMO_PORT": "x"}, {"DEMO_PORT": "70000"}, {"DEMO_LOG": "maybe"}])
def test_config_invalid(env: dict[str, str]) -> None:
    with pytest.raises(server.ConfigError):
        server.Config.from_env(env)


def test_redact_headers() -> None:
    out = server.redact_headers(
        {"Cookie": "a", "X-Session-Id": "b", "Accept": "c", "Proxy-Authorization": "d"}
    )
    assert out == {
        "cookie": "[REDACTED]",
        "x-session-id": "[REDACTED]",
        "accept": "c",
        "proxy-authorization": "[REDACTED]",
    }


def test_healthcheck(demo: server.DemoServer) -> None:
    assert server.healthcheck(demo.server_address[1]) == 0
    call(demo, "POST", "/__fault", body={"status": 503, "path": "/health"})
    assert server.healthcheck(demo.server_address[1]) == 1
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free = sock.getsockname()[1]
    sock.close()
    assert server.healthcheck(free, timeout=0.5) == 1


def test_main_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert server.main([], {"DEMO_PORT": "bad"}) == 2
    assert server.main(["--what"], {}) == 2
    err = capsys.readouterr().err
    assert "DEMO_PORT must be a port number" in err and "usage" in err


def test_main_healthcheck(demo: server.DemoServer) -> None:
    assert server.main(["--healthcheck"], {"DEMO_PORT": str(demo.server_address[1])}) == 0


def test_main_serves_until_sigterm(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    handlers: dict[int, Any] = {}
    monkeypatch.setattr(signal, "signal", handlers.__setitem__)
    result: list[int] = []
    env = {"DEMO_PORT": str(port), "DEMO_HOST": "127.0.0.1"}
    thread = threading.Thread(target=lambda: result.append(server.main([], env)), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and server.healthcheck(port, timeout=0.2) != 0:
        time.sleep(0.05)
    assert server.healthcheck(port) == 0
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    thread.join(5)
    assert result == [0]


def test_script_has_no_third_party_imports() -> None:
    source = (Path(server.__file__)).read_text()
    allowed = {
        "__future__",
        "hmac",
        "json",
        "os",
        "signal",
        "socket",
        "sys",
        "threading",
        "time",
        "urllib.error",
        "urllib.request",
        "collections",
        "dataclasses",
        "http.server",
        "typing",
        "urllib.parse",
        "collections.abc",
    }
    imported = set()
    for line in source.splitlines():
        if line.startswith(("import ", "from ")):
            imported.add(line.split()[1])
    assert imported <= allowed, imported - allowed
    assert Path(server.__file__).name == "server.py"
