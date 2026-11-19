"""OTLP/HTTP logs on the ingest host, ClickHouse query parameters, SELECT without FROM, integer
nanosecond dt, fault headers and draining oversized bodies."""

from __future__ import annotations

import gzip
import json
import socket
import urllib.parse
from datetime import UTC, datetime
from typing import Any

import otlp
import pytest
import sql
import stub
from conftest import AUTH, TABLE, ingest, pb_any, pb_field, pb_kv, query, records, req

NS = 1_700_000_000_123_456_789


def otlp_request(body: Any = "hello otlp", **extra: Any) -> bytes:
    log = (
        pb_field(1, NS, wire=1)
        + pb_field(11, NS + 5, wire=1)
        + pb_field(2, 17)
        + pb_field(3, "ERROR")
        + pb_field(5, pb_any(body))
        + pb_field(6, pb_kv("run", extra.get("run", "r1")))
        + pb_field(6, pb_kv("n", 3))
        + pb_field(6, pb_kv("ratio", 0.5))
        + pb_field(6, pb_kv("ok", True))
        + pb_field(6, pb_kv("list", ["a", 1]))
        + pb_field(6, pb_kv("map", {"k": "v"}))
        + pb_field(6, pb_kv("raw", b"\x01\x02"))
        + pb_field(7, 0)
        + pb_field(8, 1, wire=5)
        + pb_field(9, bytes.fromhex("4bf92f3577b34da6a3ce929d0e0e4736"))
        + pb_field(10, bytes.fromhex("00f067aa0ba902b7"))
        + pb_field(12, "evt")
        + pb_field(99, "unknown field is skipped")
    )
    scope = pb_field(1, pb_field(1, "probe-scope") + pb_field(2, "1.0") + pb_field(3, pb_kv("x", 1)))
    scope_logs = scope + pb_field(2, log) + pb_field(3, "schema")
    resource = pb_field(1, pb_kv("service.name", "probe-svc")) + pb_field(2, 0)
    resource_logs = pb_field(1, resource) + pb_field(2, scope_logs)
    return pb_field(1, resource_logs) + pb_field(2, "ignored top-level field")


# --- OTLP ------------------------------------------------------------------------------------------


def test_otlp_protobuf_logs_are_stored(bs: stub.Stub) -> None:
    headers = {**AUTH, "Content-Type": "application/x-protobuf"}
    status, _, body = req(bs.ingest, "POST", "/v1/logs", otlp_request(), headers)
    assert (status, body) == (200, b"")
    rec = records(bs)
    assert len(rec) == 1 and rec[0]["dt"] == "2023-11-14 22:13:20.123456"
    raw = json.loads(rec[0]["raw"])
    assert raw["message"] == "hello otlp" and raw["level"] == "ERROR" and raw["severity_number"] == 17
    assert raw["attributes"] == {"run": "r1", "n": 3, "ratio": 0.5, "ok": True, "list": ["a", 1],
                                 "map": {"k": "v"}, "raw": "AQI="}  # fmt: skip
    assert raw["resource"] == {"service.name": "probe-svc"}
    assert raw["scope"] == {"name": "probe-scope", "version": "1.0"}
    assert raw["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736" and raw["span_id"] == "00f067aa0ba902b7"
    assert raw["event_name"] == "evt"


def test_otlp_gzip_structured_body_and_observed_time(bs: stub.Stub) -> None:
    log = pb_field(11, NS, wire=1) + pb_field(5, pb_any({"a": [1, 2]}))
    payload = pb_field(1, pb_field(2, pb_field(2, log)))
    headers = {**AUTH, "Content-Type": "application/x-protobuf", "Content-Encoding": "gzip"}
    assert req(bs.ingest, "POST", "/v1/logs", gzip.compress(payload), headers)[0] == 200
    rec = records(bs)[0]
    assert rec["dt"].endswith(".123456")
    assert json.loads(json.loads(rec["raw"])["message"]) == {"a": [1, 2]}
    # neither time set -> reception time
    req(bs.ingest, "POST", "/v1/logs", pb_field(1, pb_field(2, pb_field(2, pb_field(3, "INFO")))),
        {**AUTH, "Content-Type": "application/x-protobuf"})  # fmt: skip
    assert records(bs)[1]["dt"][:4] == str(datetime.now(tz=UTC).year)


def test_otlp_json_logs(bs: stub.Stub) -> None:
    doc = {
        "resourceLogs": [{
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "json-svc"}}]},
            "scopeLogs": [{
                "scope": {"name": "s", "version": "2"},
                "logRecords": [{
                    "timeUnixNano": str(NS), "severityNumber": 9, "severityText": "INFO",
                    "body": {"stringValue": "json hello"},
                    "attributes": [
                        {"key": "i", "value": {"intValue": "7"}},
                        {"key": "d", "value": {"doubleValue": 1.5}},
                        {"key": "b", "value": {"boolValue": True}},
                        {"key": "arr", "value": {"arrayValue": {"values": [{"stringValue": "x"}]}}},
                        {"key": "kv",
                         "value": {"kvlistValue": {"values": [{"key": "k", "value": {"stringValue": "v"}}]}}},
                        {"key": "by", "value": {"bytesValue": "AQI="}},
                        {"key": "none", "value": {}},
                        {"key": "bad", "value": "not an object"},
                    ],
                    "traceId": "4BF92F3577B34DA6A3CE929D0E0E4736", "spanId": "00F067AA0BA902B7",
                }],
            }],
        }]
    }  # fmt: skip
    status, hdrs, body = req(
        bs.ingest, "POST", "/v1/logs", json.dumps(doc), {**AUTH, "Content-Type": "application/json"}
    )
    assert (status, body) == (200, b"{}") and hdrs["content-type"] == "application/json"
    raw = json.loads(records(bs)[0]["raw"])
    assert raw["message"] == "json hello" and raw["resource"] == {"service.name": "json-svc"}
    assert raw["attributes"] == {"i": 7, "d": 1.5, "b": True, "arr": ["x"], "kv": {"k": "v"}, "by": "AQI=",
                                 "none": None, "bad": None}  # fmt: skip
    assert raw["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_otlp_traces_metrics_accepted_not_stored(bs: stub.Stub) -> None:
    for path in ("/v1/traces", "/v1/metrics"):
        assert (
            req(bs.ingest, "POST", path, b"\x0a\x00", {**AUTH, "Content-Type": "application/x-protobuf"})[0]
            == 200
        )
    assert records(bs) == []
    log = json.loads(req(bs.ingest, "GET", "/__stub/requests")[2])["requests"]
    assert [e["signal"] for e in log] == ["traces", "metrics"]


@pytest.mark.parametrize(
    "body,ctype,status",
    [
        (b"\xff\xff", "application/x-protobuf", 400),
        (b"{bad", "application/json", 400),
        (b"[]", "application/json", 400),
        (
            b'{"resourceLogs": [{"scopeLogs": [{"logRecords": [{"timeUnixNano": "x"}]}]}]}',
            "application/json",
            400,
        ),
        (b'{"resourceLogs": [{"resource": {"attributes": {"k": 1}}}]}', "application/json", 400),
        (b"x", "text/plain", 415),
    ],
)
def test_otlp_errors(bs: stub.Stub, body: bytes, ctype: str, status: int) -> None:
    assert req(bs.ingest, "POST", "/v1/logs", body, {**AUTH, "Content-Type": ctype})[0] == status


def test_otlp_requires_token(bs: stub.Stub) -> None:
    assert (
        req(bs.ingest, "POST", "/v1/logs", otlp_request(), {"Content-Type": "application/x-protobuf"})[0]
        == 403
    )


def test_otlp_record_size_limit(bs: stub.Stub) -> None:
    big = otlp_request(body="x" * 2000)
    assert (
        req(bs.ingest, "POST", "/v1/logs", big, {**AUTH, "Content-Type": "application/x-protobuf"})[0] == 413
    )


@pytest.mark.parametrize(
    "data,message",
    [
        (b"\x08", "truncated varint"),
        (b"\x08" + b"\xff" * 10 + b"\x01", "varint too long"),
        (b"\x00\x01", "field number 0"),
        (b"\x09\x00", "truncated fixed64"),
        (b"\x0a\x05ab", "truncated length-delimited"),
        (b"\x0d\x00", "truncated fixed32"),
        (b"\x0b", "unsupported wire type 3"),
    ],
)
def test_protobuf_wire_errors(data: bytes, message: str) -> None:
    with pytest.raises(otlp.OtlpError, match=message):
        otlp.fields(data)


def test_protobuf_value_errors() -> None:
    with pytest.raises(otlp.OtlpError, match="invalid UTF-8"):
        otlp.any_value(pb_field(1, b"\xff"))
    with pytest.raises(otlp.OtlpError, match="expected a length-delimited string"):
        otlp._str(5)
    assert otlp.any_value(pb_field(3, -5)) == -5
    assert otlp.any_value(b"") is None


# --- query parameters, SELECT without FROM ---------------------------------------------------------


def test_query_parameters_over_http(bs: stub.Stub) -> None:
    ingest(bs, json.dumps([{"message": "it's run-9 %literal%", "dt": 1700000001}, {"message": "other"}]))
    params = urllib.parse.urlencode(
        {"param_needle": "it's run-9 %literal%", "param_t": f"{TABLE}_logs", "param_lim": "10"}
    )
    text = (
        "SELECT raw FROM remote({t:Identifier}) WHERE position(raw, {needle:String}) > 0 "
        "LIMIT {lim:UInt32} FORMAT JSONEachRow"
    )
    status, _, body = query(bs, text, path=f"/?{params}")
    assert status == 200 and len(body.splitlines()) == 1
    status, _, body = query(bs, "SELECT {missing:String}")
    assert status == 400 and "UNKNOWN_QUERY_PARAMETER" in body
    status, _, body = query(bs, "SELECT {n:UInt8}", path="/?param_n=-1")
    assert status == 400 and "BAD_QUERY_PARAMETER" in body


def test_select_without_from_over_http(bs: stub.Stub) -> None:
    assert query(bs, "SELECT 1")[2] == "1\n"
    status, _, body = query(bs, "SELECT version() AS v FORMAT JSONEachRow")
    assert status == 200 and json.loads(body) == {"v": sql.VERSION}


@pytest.mark.parametrize(
    "type_name,raw,expected",
    [
        ("String", "a'b", "a'b"),
        ("FixedString(3)", "abc", "abc"),
        ("UUID", "u", "u"),
        ("Int64", "-5", -5),
        ("UInt64", "5", 5),
        ("Float64", "1.5", 1.5),
        ("Decimal(10, 2)", "2.25", 2.25),
        ("Bool", "true", True),
        ("Bool", "0", False),
        ("DateTime", "2026-01-01 00:00:00", datetime(2026, 1, 1, tzinfo=UTC)),
        ("DateTime64(3)", "1700000000", datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)),
        ("Date", "2026-01-02", datetime(2026, 1, 2, tzinfo=UTC)),
        ("Nullable(String)", "\\N", None),
        ("Nullable(Int64)", "4", 4),
    ],
)
def test_bind_parameter_types(type_name: str, raw: str, expected: Any) -> None:
    rows = sql.execute(f"SELECT {{p:{type_name}}} AS v", lambda k, t: ([], []), params={"p": raw})[2]
    assert rows == [{"v": expected}]


@pytest.mark.parametrize(
    "type_name,raw,code",
    [
        ("Int64", "x", 457),
        ("UInt8", "-1", 457),
        ("Float64", "abc", 457),
        ("Bool", "maybe", 457),
        ("DateTime", "yesterday", 457),
        ("Array(String)", "['a']", 457),
    ],
)
def test_bind_parameter_errors(type_name: str, raw: str, code: int) -> None:
    with pytest.raises(sql.SqlError) as info:
        sql.execute(f"SELECT {{p:{type_name}}}", lambda k, t: ([], []), params={"p": raw})
    assert info.value.code == code


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("plain", "plain"),
        ("a\\\\b", "a\\b"),  # \\ -> backslash
        ("tab\\there", "tab\there"),
        ("line\\nbreak\\r", "line\nbreak\r"),
        ("\\0\\b\\f\\a\\v", "\0\b\f\a\v"),
        ('it\\\'s \\"q\\"', 'it\'s "q"'),
        ("\\x", "x"),  # unknown escape: backslash dropped
        ("end\\", "end\\"),  # trailing backslash kept
    ],
)
def test_unescape_param_clickhouse_tsv_rules(raw: str, expected: str) -> None:
    assert sql.unescape_param(raw) == expected


def test_string_parameter_is_tsv_unescaped() -> None:
    rows = sql.execute("SELECT {p:String} AS v", lambda k, t: ([], []), params={"p": "a\\tb\\\\c"})[2]
    assert rows == [{"v": "a\tb\\c"}]
    rows = sql.execute("SELECT {p:Nullable(String)} AS v", lambda k, t: ([], []), params={"p": "\\N"})[2]
    assert rows == [{"v": None}]


def test_identifier_parameter_and_limit_parameter() -> None:
    def resolver(kind: str, table: str) -> tuple[list[str], list[dict[str, Any]]]:
        assert (kind, table) == ("remote", "t1_x_logs")
        return ["dt", "raw"], [{"dt": 1, "raw": "a"}, {"dt": 2, "raw": "b"}]

    rows = sql.execute(
        "SELECT raw FROM remote({t:Identifier}) LIMIT {n:UInt8}",
        resolver,
        params={"t": "t1_x_logs", "n": "1"},
    )
    assert rows[2] == [{"raw": "a"}]
    with pytest.raises(sql.SqlError, match="unsigned"):
        sql.execute("SELECT raw FROM remote(t1_x_logs) LIMIT {n:Int8}", resolver, params={"n": "-1"})
    with pytest.raises(sql.SqlError, match="version"):
        sql.execute("SELECT version(1)", resolver)


# --- dt integer math, fault headers, drain ------------------------------------------------------------


@pytest.mark.parametrize(
    "dt,expected",
    [
        (1_700_000_000_123_456_789, "2023-11-14 22:13:20.123456"),
        (1_700_000_000_123_456_999, "2023-11-14 22:13:20.123456"),
        (1_700_000_000_123_456, "2023-11-14 22:13:20.123456"),
        (1_700_000_000_123, "2023-11-14 22:13:20.123000"),
        (1_700_000_000.5, "2023-11-14 22:13:20.500000"),
        (1_700_000_000_123.0, "2023-11-14 22:13:20.123000"),
        (1_700_000_000_123_456.0, "2023-11-14 22:13:20.123456"),
        (1.7e18, "2023-11-14 22:13:20.000000"),
    ],
)
def test_dt_integer_and_float(bs: stub.Stub, dt: Any, expected: str) -> None:
    assert ingest(bs, json.dumps({"message": "t", "dt": dt}))[0] == 202
    assert records(bs)[0]["dt"] == expected


def test_event_time_overflow() -> None:
    received = datetime(2026, 1, 1, tzinfo=UTC)
    assert stub.event_time(10**40, received) is received
    assert stub.event_time(-(10**40), received) is received


def test_fault_headers_ingest_and_query(bs: stub.Stub) -> None:
    req(bs.ingest, "POST", "/__stub/fault", '{"status": 429, "retryAfter": 2, "headers": {"X-Extra": "1"}}')
    status, headers, _ = req(bs.ingest, "POST", "/", '{"m":1}', {**AUTH, "Content-Type": "application/json"})
    assert status == 429 and headers["retry-after"] == "2" and headers["x-extra"] == "1"
    req(
        bs.ingest,
        "POST",
        "/__stub/fault",
        '{"status": 503, "target": "query", "headers": {"Retry-After": "1"}}',
    )
    status, headers, _ = query(bs, "SELECT 1")
    assert status == 503 and headers["retry-after"] == "1"
    for bad, message in (
        ('{"headers": {"a": 1}}', "headers must map"),
        ('{"retryAfter": true}', "retryAfter must be"),
    ):
        status, _, payload = req(bs.ingest, "POST", "/__stub/fault", bad)
        assert status == 400 and message in json.loads(payload)["error"]


def test_oversized_body_is_drained_before_413(bs: stub.Stub) -> None:
    body = b'{"m":"' + b"x" * 200_000 + b'"}'
    sock = socket.create_connection(("127.0.0.1", bs.ingest.server_address[1]), timeout=5)
    head = (
        f"POST / HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer unit-source-token\r\n"
        f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
    ).encode()
    sock.sendall(head + body)  # would raise BrokenPipe/ConnectionReset if the server did not read it
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            break
        response += chunk
    sock.close()
    assert response.startswith(b"HTTP/1.1 413")


def test_drain_cap_and_chunked_drain_paths(bs: stub.Stub, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stub, "MAX_DRAIN_BYTES", 5000)
    # chunked: first chunk crosses the limit, the rest is drained (bounded), bad trailer stops draining
    for tail in (
        b"10\r\n" + b"y" * 16 + b"\r\n0\r\n\r\n",
        b"zz\r\n",
        b"1000\r\n" + b"z" * 100,  # chunk larger than the remaining drain budget; client stops early
    ):
        sock = socket.create_connection(("127.0.0.1", bs.ingest.server_address[1]), timeout=5)
        sock.sendall(
            b"POST / HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer unit-source-token\r\n"
            b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
            + b"1100\r\n" + b"x" * 0x1100 + b"\r\n" + tail
        )  # fmt: skip
        sock.shutdown(socket.SHUT_WR)  # EOF: nothing stays unread, so no RST can drop the answer
        assert sock.recv(4096).startswith(b"HTTP/1.1 413")
        sock.close()
    # Content-Length larger than the drain cap and a client that stops sending early
    sock = socket.create_connection(("127.0.0.1", bs.ingest.server_address[1]), timeout=5)
    sock.sendall(b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 9000\r\n\r\n" + b"x" * 100)
    sock.shutdown(socket.SHUT_WR)
    assert sock.recv(4096).startswith(b"HTTP/1.1 413")
    sock.close()
