from __future__ import annotations

import base64
import http.client
import json
import struct
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stub

TOKEN = "unit-source-token"
TABLE = "t7_unit"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BASIC = {"Authorization": "Basic " + base64.b64encode(b"stub-user:stub-password").decode()}


@pytest.fixture()
def bs() -> Iterator[stub.Stub]:
    cfg = stub.Config(
        host="127.0.0.1",
        ingest_port=0,
        query_port=0,
        sources={TOKEN: TABLE, "other": "t8_other"},
        max_request_bytes=4096,
        max_record_bytes=1024,
        max_records=50,
        log=True,
    )
    s = stub.Stub(cfg)
    s.start(poll_interval=0.01)
    yield s
    s.stop()


def req(
    srv: stub.StubServer,
    method: str,
    path: str = "/",
    body: bytes | str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    data = body.encode() if isinstance(body, str) else body
    conn.request(method, path, body=data, headers=headers or {})
    resp = conn.getresponse()
    payload = resp.read()
    conn.close()
    return resp.status, {k.lower(): v for k, v in resp.getheaders()}, payload


def ingest(
    s: stub.Stub, body: bytes | str, ctype: str = "application/json", **extra: str
) -> tuple[int, bytes]:
    headers = {**AUTH, "Content-Type": ctype, **extra}
    status, _, payload = req(s.ingest, "POST", "/", body, headers)
    return status, payload


def query(
    s: stub.Stub, sql_text: str, headers: dict[str, str] | None = None, path: str = "/"
) -> tuple[int, dict[str, str], str]:
    status, hdrs, payload = req(
        s.query, "POST", path, sql_text, {**BASIC, "Content-Type": "plain/text", **(headers or {})}
    )
    return status, hdrs, payload.decode()


def records(s: stub.Stub) -> list[dict[str, Any]]:
    return json.loads(req(s.ingest, "GET", "/__stub/records")[2])["records"]


def packb(value: Any) -> bytes:
    """Small MessagePack encoder used to build test payloads (covers the forms the decoder reads)."""
    if value is None:
        return b"\xc0"
    if value is True:
        return b"\xc3"
    if value is False:
        return b"\xc2"
    if isinstance(value, int):
        if 0 <= value <= 0x7F:
            return bytes([value])
        if -32 <= value < 0:
            return struct.pack(">b", value)
        if 0 <= value <= 0xFF:
            return b"\xcc" + struct.pack(">B", value)
        if 0 <= value <= 0xFFFF:
            return b"\xcd" + struct.pack(">H", value)
        if 0 <= value <= 0xFFFFFFFF:
            return b"\xce" + struct.pack(">I", value)
        if value >= 0:
            return b"\xcf" + struct.pack(">Q", value)
        if value >= -0x80:
            return b"\xd0" + struct.pack(">b", value)
        if value >= -0x8000:
            return b"\xd1" + struct.pack(">h", value)
        if value >= -0x80000000:
            return b"\xd2" + struct.pack(">i", value)
        return b"\xd3" + struct.pack(">q", value)
    if isinstance(value, float):
        return b"\xcb" + struct.pack(">d", value)
    if isinstance(value, str):
        data = value.encode()
        if len(data) < 32:
            return bytes([0xA0 | len(data)]) + data
        if len(data) <= 0xFF:
            return b"\xd9" + struct.pack(">B", len(data)) + data
        if len(data) <= 0xFFFF:
            return b"\xda" + struct.pack(">H", len(data)) + data
        return b"\xdb" + struct.pack(">I", len(data)) + data
    if isinstance(value, bytes):
        return b"\xc4" + struct.pack(">B", len(value)) + value
    if isinstance(value, list):
        head = bytes([0x90 | len(value)]) if len(value) < 16 else b"\xdc" + struct.pack(">H", len(value))
        return head + b"".join(packb(v) for v in value)
    if isinstance(value, dict):
        head = bytes([0x80 | len(value)]) if len(value) < 16 else b"\xde" + struct.pack(">H", len(value))
        return head + b"".join(packb(k) + packb(v) for k, v in value.items())
    if isinstance(value, datetime):
        seconds = int(value.timestamp())
        nanos = value.microsecond * 1000
        return b"\xd7\xff" + struct.pack(">Q", (nanos << 34) | seconds)
    raise TypeError(type(value))


# --- protobuf (test-only encoder for OTLP payloads) ---------------------------------------------


def pb_varint(value: int) -> bytes:
    value &= (1 << 64) - 1
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def pb_field(number: int, value: Any, wire: int | None = None) -> bytes:
    if isinstance(value, (bytes, str)):
        data = value.encode() if isinstance(value, str) else value
        return pb_varint(number << 3 | 2) + pb_varint(len(data)) + data
    if wire == 1:
        return pb_varint(number << 3 | 1) + struct.pack("<Q", value)
    if wire == 5:
        return pb_varint(number << 3 | 5) + struct.pack("<I", value)
    return pb_varint(number << 3) + pb_varint(int(value))


def pb_any(value: Any) -> bytes:
    if isinstance(value, str):
        return pb_field(1, value)
    if isinstance(value, bool):
        return pb_field(2, int(value))
    if isinstance(value, int):
        return pb_field(3, value)
    if isinstance(value, float):
        return pb_field(4, struct.unpack("<Q", struct.pack("<d", value))[0], wire=1)
    if isinstance(value, list):
        return pb_field(5, b"".join(pb_field(1, pb_any(v)) for v in value))
    if isinstance(value, dict):
        return pb_field(6, b"".join(pb_field(1, pb_kv(k, v)) for k, v in value.items()))
    if isinstance(value, bytes):
        return pb_field(7, value)
    raise TypeError(type(value))


def pb_kv(key: str, value: Any) -> bytes:
    return pb_field(1, key) + pb_field(2, pb_any(value))
