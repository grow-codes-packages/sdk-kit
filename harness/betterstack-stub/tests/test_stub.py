from __future__ import annotations

import base64
import gzip
import json
import signal
import socket
import threading
import time
from datetime import UTC, datetime
from typing import Any

import pytest
import stub
from conftest import AUTH, BASIC, TABLE, TOKEN, ingest, packb, query, records, req

# --- ingest: documented behaviour -------------------------------------------------------------------


def test_single_event_json_202_empty_body(bs: stub.Stub) -> None:
    assert ingest(bs, '{"message":"logs is ready","nested":{"values":123}}') == (202, b"")
    rec = records(bs)
    assert len(rec) == 1 and rec[0]["table"] == TABLE
    assert json.loads(rec[0]["raw"]) == {"message": "logs is ready", "nested": {"values": 123}}


def test_array_ndjson_msgpack_gzip(bs: stub.Stub) -> None:
    assert ingest(bs, '[{"message":"A"},{"message":"B"}]')[0] == 202
    assert ingest(bs, '{"message":"C"}\n\n{"message":"D"}\n', "application/x-ndjson")[0] == 202
    assert ingest(bs, '[{"message":"E"}]', "application/x-ndjson; charset=utf-8")[0] == 202
    assert (
        ingest(bs, packb([{"message": "F"}, {"message": "G", "bin": b"\xff\x00"}]), "application/msgpack")[0]
        == 202
    )
    zipped = gzip.compress(packb({"message": "H", "dt": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)}))
    assert ingest(bs, zipped, "application/msgpack", **{"Content-Encoding": "gzip"})[0] == 202
    assert ingest(bs, '{"message":"I"}', **{"Content-Encoding": "identity"})[0] == 202
    raws = [json.loads(r["raw"]) for r in records(bs)]
    assert [r["message"] for r in raws] == list("ABCDEFGHI")
    assert raws[6]["bin"] == "/wA="  # non-UTF-8 bin -> base64
    assert raws[7]["dt"] == "2026-01-02T03:04:05Z"
    assert records(bs)[7]["dt"] == "2026-01-02 03:04:05.000000"


def test_empty_array_is_accepted(bs: stub.Stub) -> None:
    assert ingest(bs, "[]")[0] == 202
    assert records(bs) == []


@pytest.mark.parametrize(
    "dt,expected",
    [
        (1672490759, "2022-12-31 12:45:59.000000"),
        (1672490759123, "2022-12-31 12:45:59.123000"),
        (1672490759123456, "2022-12-31 12:45:59.123456"),
        (1672490759123456000, "2022-12-31 12:45:59.123456"),
        ("1672490759", "2022-12-31 12:45:59.000000"),
        ("2022-12-31T13:45:59.123456Z", "2022-12-31 13:45:59.123456"),
        ("2022-12-31 13:45:59.123456+02:00", "2022-12-31 11:45:59.123456"),
        ("2023-08-09 07:03:30+00:00", "2023-08-09 07:03:30.000000"),
        ("2022-12-31T13:45:59.123456789Z", "2022-12-31 13:45:59.123456"),
        ("2022-12-31T13:45:59", "2022-12-31 13:45:59.000000"),
    ],
)
def test_dt_rules(bs: stub.Stub, dt: Any, expected: str) -> None:
    assert ingest(bs, json.dumps({"message": "t", "dt": dt}))[0] == 202
    assert records(bs)[0]["dt"] == expected


@pytest.mark.parametrize("dt", ["not a time", True, {"x": 1}, 1e30])
def test_unparseable_dt_uses_reception_time_and_keeps_value(bs: stub.Stub, dt: Any) -> None:
    before = datetime.now(tz=UTC).replace(microsecond=0)
    assert ingest(bs, json.dumps({"message": "t", "dt": dt}))[0] == 202
    rec = records(bs)[0]
    assert datetime.fromisoformat(rec["dt"]).replace(tzinfo=UTC) >= before
    assert json.loads(rec["raw"])["dt"] == dt


def test_missing_dt_uses_reception_time(bs: stub.Stub) -> None:
    ingest(bs, '{"message":"no dt"}')
    rec = records(bs)[0]
    assert rec["dt"][:10] == datetime.now(tz=UTC).strftime("%Y-%m-%d")


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {TOKEN}"}, {"Authorization": "Bearer"}],
)
def test_invalid_source_token_403(bs: stub.Stub, headers: dict[str, str]) -> None:
    status, _, body = req(
        bs.ingest, "POST", "/", '{"message":"x"}', {"Content-Type": "application/json", **headers}
    )
    assert (status, body) == (403, b"Unauthorized")
    assert records(bs) == []


@pytest.mark.parametrize(
    "body,ctype",
    [
        ("{not json", "application/json"),
        ('"just a string"', "application/json"),
        ("[1, 2]", "application/json"),
        ('{"a":1}\n[3]', "application/x-ndjson"),
        ("\xff", "application/json"),
        (b"\xc1", "application/msgpack"),
        (b"\x01", "application/msgpack"),
        ('{"a":1}', "text/plain"),
        ('{"a":1}', ""),
    ],
)
def test_invalid_body_406(bs: stub.Stub, body: Any, ctype: str) -> None:
    assert ingest(bs, body, ctype) == (406, b"Couldn't parse JSON content.")


def test_bad_gzip_406_and_unknown_encoding_415(bs: stub.Stub) -> None:
    assert ingest(bs, b"not gzip", **{"Content-Encoding": "gzip"})[0] == 406
    truncated = gzip.compress(b'{"message":"x"}')[:-6]
    assert ingest(bs, truncated, **{"Content-Encoding": "gzip"})[0] == 406
    assert ingest(bs, '{"a":1}', **{"Content-Encoding": "br"})[0] == 415


def test_size_limits_413(bs: stub.Stub) -> None:
    assert ingest(bs, json.dumps({"m": "x" * 5000})) == (413, b"payload reached size limit")
    assert ingest(bs, json.dumps({"m": "x" * 2000})) == (413, b"payload reached size limit")  # record > 1024
    # compressed size counts: a 3000-byte record compresses below the 4096 request limit, but is
    # still a record over 1024 bytes
    assert (
        ingest(bs, gzip.compress(json.dumps({"m": "y" * 3000}).encode()), **{"Content-Encoding": "gzip"})[0]
        == 413
    )
    bomb = gzip.compress(b"[" + b'{"m":1},' * 10000 + b'{"m":1}]')
    assert len(bomb) < 4096
    assert ingest(bs, bomb, **{"Content-Encoding": "gzip"})[0] == 413  # inflates past 8 x limit


def test_chunked_body(bs: stub.Stub) -> None:
    sock = socket.create_connection(("127.0.0.1", bs.ingest.server_address[1]), timeout=5)
    body = b'{"message":"chunked"}'
    chunked = f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
    sock.sendall(
        b"POST / HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer " + TOKEN.encode()
        + b"\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n" + chunked
    )  # fmt: skip
    assert sock.recv(4096).startswith(b"HTTP/1.1 202")
    sock.close()
    assert json.loads(records(bs)[0]["raw"]) == {"message": "chunked"}


def test_chunked_errors(bs: stub.Stub) -> None:
    big = b"2000\r\n" + b"x" * 0x2000 + b"\r\n" + b"10\r\n" + b"y" * 16 + b"\r\n0\r\n\r\n"
    for chunked, status in ((b"zz\r\n", b"400"), (big, b"413")):
        sock = socket.create_connection(("127.0.0.1", bs.ingest.server_address[1]), timeout=5)
        sock.sendall(
            b"POST / HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer " + TOKEN.encode()
            + b"\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n" + chunked
        )  # fmt: skip
        assert sock.recv(4096).startswith(b"HTTP/1.1 " + status)
        sock.close()


def test_bad_content_length(bs: stub.Stub) -> None:
    sock = socket.create_connection(("127.0.0.1", bs.ingest.server_address[1]), timeout=5)
    sock.sendall(b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: nope\r\n\r\n")
    assert sock.recv(4096).startswith(b"HTTP/1.1 400")
    sock.close()


def test_wrong_path_and_method(bs: stub.Stub) -> None:
    assert req(bs.ingest, "POST", "/v2/logs", "{}", AUTH)[0] == 404
    status, headers, _ = req(bs.ingest, "GET", "/", None, AUTH)
    assert status == 405 and headers["allow"] == "POST"
    assert req(bs.ingest, "HEAD", "/", None, AUTH)[0] == 405


def test_second_source_and_retention(bs: stub.Stub) -> None:
    status, _, _ = req(
        bs.ingest,
        "POST",
        "/",
        '{"message":"o"}',
        {"Authorization": "Bearer other", "Content-Type": "application/json"},
    )
    assert status == 202
    assert [r["table"] for r in records(bs)] == ["t8_other"]
    other = json.loads(req(bs.ingest, "GET", "/__stub/records?table=t8_other")[2])["records"]
    assert len(other) == 1
    ingest(bs, json.dumps([{"i": i} for i in range(60)]))
    assert len(records(bs)) == 50  # max_records keeps the newest


def test_fault_402_then_normal(bs: stub.Stub) -> None:
    status, _, body = req(bs.ingest, "POST", "/__stub/fault", '{"status": 402, "count": 2}')
    assert (status, json.loads(body)) == (200, {"queued": 1})
    assert ingest(bs, '{"m":1}') == (402, b"Quota exceeded")
    assert ingest(bs, '{"m":1}') == (402, b"Quota exceeded")
    assert ingest(bs, '{"m":1}')[0] == 202
    req(bs.ingest, "POST", "/__stub/fault", '{"status": 503, "body": "busy"}')
    assert ingest(bs, '{"m":1}') == (503, b"busy")
    req(bs.ingest, "POST", "/__stub/fault", '{"status": 500}')
    assert req(bs.ingest, "DELETE", "/__stub/fault")[0] == 204
    assert ingest(bs, '{"m":1}')[0] == 202


@pytest.mark.parametrize(
    "body,message",
    [
        ("[1]", "fault must be an object"),
        ('{"status": 99}', "status must be an HTTP status code"),
        ('{"count": 0}', "count must be a positive integer"),
        ('{"target": "x"}', "target must be ingest or query"),
        ('{"body": 1}', "body must be a string"),
        ("{bad", "Expecting property name"),
    ],
)
def test_fault_validation(bs: stub.Stub, body: str, message: str) -> None:
    status, _, payload = req(bs.ingest, "POST", "/__stub/fault", body)
    assert status == 400 and message in json.loads(payload)["error"]


def test_requests_log_reset_health(bs: stub.Stub) -> None:
    ingest(bs, gzip.compress(b'{"m":1}'), **{"Content-Encoding": "gzip"})
    log = json.loads(req(bs.ingest, "GET", "/__stub/requests")[2])["requests"]
    assert log[0]["contentEncoding"] == "gzip" and log[0]["status"] == 202 and log[0]["records"] == 1
    assert TOKEN not in json.dumps(log)
    assert json.loads(req(bs.query, "GET", "/__stub/health")[2]) == {"status": "ok", "role": "query"}
    assert req(bs.ingest, "DELETE", "/__stub/records")[0] == 204
    assert records(bs) == []
    assert req(bs.ingest, "POST", "/__stub/reset")[0] == 204
    assert json.loads(req(bs.ingest, "GET", "/__stub/requests")[2]) == {"requests": []}
    assert req(bs.ingest, "GET", "/__stub/nope")[0] == 404


# --- query ---------------------------------------------------------------------------------------------


def seed(bs: stub.Stub) -> None:
    ingest(bs, json.dumps([
        {"message": "conformance hello r1", "dt": 1700000001, "level": "INFO"},
        {"message": "conformance error r1", "dt": 1700000002, "level": "ERROR"},
        {"message": "other r2", "dt": 1700000003, "level": "INFO"},
    ]))  # fmt: skip


def test_documented_query_shape(bs: stub.Stub) -> None:
    seed(bs)
    status, headers, body = query(
        bs,
        f"""SELECT dt, raw FROM (
              SELECT dt, raw FROM remote({TABLE}_logs)
              UNION ALL
              SELECT dt, raw FROM s3Cluster(primary, {TABLE}_s3) WHERE _row_type = 1
            ) WHERE raw LIKE '%r1%' ORDER BY dt DESC LIMIT 5000 FORMAT JSONEachRow""",
    )
    assert status == 200
    assert headers["x-clickhouse-format"] == "JSONEachRow"
    rows = [json.loads(line) for line in body.splitlines()]
    assert [json.loads(r["raw"])["message"] for r in rows] == ["conformance error r1", "conformance hello r1"]
    assert rows[0]["dt"] == "2023-11-14 22:13:22.000000"


def test_query_auth_variants(bs: stub.Stub) -> None:
    seed(bs)
    sql_text = f"SELECT count() FROM remote({TABLE}_logs) FORMAT JSONEachRow"
    for headers, path in (
        ({"X-ClickHouse-User": "stub-user", "X-ClickHouse-Key": "stub-password"}, "/"),
        ({}, "/?user=stub-user&password=stub-password"),
    ):
        status, _, body = req(bs.query, "POST", path, sql_text, headers)
        assert (status, json.loads(body)) == (200, {"count()": "3"})
    status, _, body = req(bs.query, "GET", f"/?query={sql_text.replace(' ', '%20')}", None, BASIC)
    assert (status, json.loads(body)) == (200, {"count()": "3"})
    bad = {"Authorization": "Basic " + base64.b64encode(b"stub-user:nope").decode()}
    for headers in (bad, {}, {"Authorization": "Basic !!!"}, {"Authorization": "Bearer x"}):
        status, hdrs, body = req(bs.query, "POST", "/", sql_text, headers)
        assert status == 401 and b"Code: 516" in body and hdrs["x-clickhouse-exception-code"] == "516"


def test_query_formats_and_settings(bs: stub.Stub) -> None:
    seed(bs)
    base = f"SELECT JSONExtractString(raw, 'level') AS level FROM remote({TABLE}_logs) ORDER BY dt"
    assert query(bs, base)[2] == "INFO\nERROR\nINFO\n"  # ClickHouse default: TabSeparated
    status, headers, body = query(bs, base, path="/?default_format=JSONEachRow")
    assert json.loads(body.splitlines()[0]) == {"level": "INFO"}
    _, _, body = query(bs, base + " FORMAT JSONEachRow", path="/?output_format_json_array_of_rows=1")
    assert json.loads(body) == [{"level": "INFO"}, {"level": "ERROR"}, {"level": "INFO"}]
    _, headers, body = query(bs, base + " FORMAT JSON")
    assert headers["content-type"].startswith("application/json") and json.loads(body)["rows"] == 3
    status, _, body = query(bs, base, path="/?default_format=Avro")
    assert status == 404 and "UNKNOWN_FORMAT" in body


def test_query_spans_metrics_and_errors(bs: stub.Stub) -> None:
    seed(bs)
    assert query(bs, f"SELECT dt, raw FROM remote({TABLE}_spans) FORMAT JSONEachRow")[:1] == (200,)
    assert query(bs, f"SELECT dt, raw FROM remote({TABLE}_spans) FORMAT JSONEachRow")[2] == ""
    assert query(bs, f"SELECT raw FROM remote({TABLE}_metrics)")[2] == ""
    cases = [
        ("SELECT raw FROM remote(t9_missing_logs)", 404, "UNKNOWN_TABLE"),
        ("SELECT raw FROM s3Cluster(primary, t9_s3)", 404, "UNKNOWN_TABLE"),
        (f"SELECT nope FROM remote({TABLE}_logs)", 404, "UNKNOWN_IDENTIFIER"),
        (f"SELECT foo(raw) FROM remote({TABLE}_logs)", 404, "UNKNOWN_FUNCTION"),
        (f"SELECT raw FROM remote({TABLE}_logs) FORMAT Avro", 404, "UNKNOWN_FORMAT"),
        (f"SELECT raw FROM remote({TABLE}_logs) GROUP BY raw", 501, "NOT_IMPLEMENTED"),
        ("SELEC 1", 400, "SYNTAX_ERROR"),
        ("   ", 400, "SYNTAX_ERROR"),
    ]
    for text, status, name in cases:
        got_status, _, body = query(bs, text)
        assert got_status == status and name in body and body.startswith("Code: "), (text, got_status, body)
    assert query(bs, "SELECT 1", path="/nope")[0] == 404
    assert req(bs.query, "GET", "/ping")[2] == b"Ok.\n"
    huge = "SELECT raw FROM remote(x) WHERE raw LIKE '" + "a" * (300 * 1024) + "'"
    assert query(bs, huge)[0] == 413


def test_query_fault(bs: stub.Stub) -> None:
    req(
        bs.query, "POST", "/__stub/fault", '{"status": 503, "target": "query", "body": "Code: 202. too many"}'
    )
    assert query(bs, "SELECT 1")[:1] == (503,)
    assert ingest(bs, '{"m":1}')[0] == 202  # ingest faults are separate
    log = json.loads(req(bs.query, "GET", "/__stub/requests")[2])["requests"]
    assert [e["target"] for e in log] == ["ingest"]


def test_search_like_the_sdk(bs: stub.Stub) -> None:
    run = "abc123xy"
    ingest(bs, json.dumps({"message": f"conformance hello {run}", "attributes": {"run": run}}))
    ingest(bs, packb({"message": f"conformance error {run}", "level": "ERROR"}), "application/msgpack")
    text = (
        f"SELECT dt, raw FROM remote({TABLE}_logs) WHERE raw LIKE '%{run}%' "
        f"AND dt >= now() - INTERVAL 10 MINUTE ORDER BY dt DESC LIMIT 100 FORMAT JSONEachRow"
    )
    status, _, body = query(bs, text)
    assert status == 200 and len(body.splitlines()) == 2


# --- config, health, main ----------------------------------------------------------------------------------


def test_config_from_env() -> None:
    assert stub.Config.from_env({}) == stub.Config()
    cfg = stub.Config.from_env({
        "BETTERSTACK_STUB_SOURCES": "a=t1_a, b=t2_b",
        "BETTERSTACK_STUB_INGEST_PORT": "9000",
        "BETTERSTACK_STUB_QUERY_PORT": "9001",
        "BETTERSTACK_STUB_QUERY_USER": "u",
        "BETTERSTACK_STUB_QUERY_PASSWORD": "p",
        "BETTERSTACK_STUB_MAX_RECORDS": "5",
        "BETTERSTACK_STUB_LOG": "yes",
        "BETTERSTACK_STUB_HOST": "127.0.0.1",
    })  # fmt: skip
    assert cfg.sources == {"a": "t1_a", "b": "t2_b"} and cfg.ingest_port == 9000 and cfg.query_port == 9001
    assert (cfg.query_user, cfg.query_password, cfg.max_records, cfg.log, cfg.host) == (
        "u",
        "p",
        5,
        True,
        "127.0.0.1",
    )


@pytest.mark.parametrize(
    "env",
    [
        {"BETTERSTACK_STUB_SOURCES": "nope"},
        {"BETTERSTACK_STUB_SOURCES": "a=bad-table"},
        {"BETTERSTACK_STUB_SOURCES": "=t1"},
        {"BETTERSTACK_STUB_INGEST_PORT": "99999"},
        {"BETTERSTACK_STUB_MAX_RECORDS": "0"},
        {"BETTERSTACK_STUB_MAX_RECORD_BYTES": "x"},
    ],
)
def test_config_invalid(env: dict[str, str]) -> None:
    with pytest.raises(stub.ConfigError):
        stub.Config.from_env(env)


def test_event_time_edge_cases() -> None:
    received = datetime(2026, 1, 1, tzinfo=UTC)
    assert stub.event_time(None, received) is received
    assert stub.event_time(10**30, received) is received
    assert stub.event_time(datetime(2026, 2, 2, tzinfo=UTC), received) == datetime(2026, 2, 2, tzinfo=UTC)


def test_healthcheck(bs: stub.Stub) -> None:
    cfg = stub.Config(ingest_port=bs.ingest.server_address[1], query_port=bs.query.server_address[1])
    assert stub.healthcheck(cfg) == 0
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free = sock.getsockname()[1]
    sock.close()
    assert stub.healthcheck(stub.Config(ingest_port=free, query_port=free), timeout=0.5) == 1


def test_main_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert stub.main([], {"BETTERSTACK_STUB_SOURCES": "x"}) == 2
    assert stub.main(["--nope"], {}) == 2
    assert "usage" in capsys.readouterr().err


def test_main_serves_until_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    ports = []
    for _ in range(2):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        ports.append(sock.getsockname()[1])
        sock.close()
    env = {"BETTERSTACK_STUB_INGEST_PORT": str(ports[0]), "BETTERSTACK_STUB_QUERY_PORT": str(ports[1]),
           "BETTERSTACK_STUB_HOST": "127.0.0.1"}  # fmt: skip
    handlers: dict[int, Any] = {}
    monkeypatch.setattr(signal, "signal", handlers.__setitem__)
    result: list[int] = []
    thread = threading.Thread(target=lambda: result.append(stub.main([], env)), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and stub.main(["--healthcheck"], env) != 0:
        time.sleep(0.05)
    assert stub.main(["--healthcheck"], env) == 0
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    thread.join(5)
    assert result == [0]
