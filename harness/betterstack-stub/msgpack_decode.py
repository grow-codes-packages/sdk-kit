"""Minimal MessagePack decoder (standard library only) for the Better Stack intake stub.

Implements the full MessagePack type system from https://github.com/msgpack/msgpack/blob/master/spec.md
except application ext types: nil, bool, int, float, str, bin, array, map and the timestamp
extension (type -1, 32/64/96-bit forms), which decodes to a timezone-aware ``datetime``.
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime, timedelta
from typing import Any

MAX_DEPTH = 64
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class MsgpackError(ValueError):
    """The payload is not valid MessagePack (or uses an unsupported ext type)."""


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, n: int) -> bytes:
        end = self.pos + n
        if end > len(self.data):
            raise MsgpackError("truncated MessagePack data")
        chunk = self.data[self.pos : end]
        self.pos = end
        return chunk

    def unpack(self, fmt: str) -> Any:
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]


def _timestamp(payload: bytes) -> datetime:
    if len(payload) == 4:
        seconds, nanos = struct.unpack(">I", payload)[0], 0
    elif len(payload) == 8:
        value = struct.unpack(">Q", payload)[0]
        nanos, seconds = value >> 34, value & 0x3_FFFF_FFFF
    elif len(payload) == 12:
        nanos, seconds = struct.unpack(">Iq", payload)
    else:
        raise MsgpackError("invalid timestamp extension length")
    if nanos > 999_999_999:
        raise MsgpackError("invalid timestamp nanoseconds")
    try:
        return _EPOCH + timedelta(seconds=seconds, microseconds=nanos // 1000)
    except OverflowError as exc:
        raise MsgpackError("timestamp out of range") from exc


def _ext(reader: _Reader, length: int) -> Any:
    ext_type = reader.unpack(">b")
    payload = reader.take(length)
    if ext_type == -1:
        return _timestamp(payload)
    raise MsgpackError(f"unsupported MessagePack ext type {ext_type}")


def _str(reader: _Reader, length: int) -> str:
    try:
        return reader.take(length).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MsgpackError("invalid UTF-8 in MessagePack str") from exc


def _decode(reader: _Reader, depth: int) -> Any:
    if depth > MAX_DEPTH:
        raise MsgpackError("MessagePack nesting too deep")
    b = reader.unpack(">B")
    if b <= 0x7F:
        return b
    if b >= 0xE0:
        return b - 0x100
    if 0xA0 <= b <= 0xBF:
        return _str(reader, b & 0x1F)
    if 0x90 <= b <= 0x9F:
        return [_decode(reader, depth + 1) for _ in range(b & 0x0F)]
    if 0x80 <= b <= 0x8F:
        return _map(reader, b & 0x0F, depth)
    simple: dict[int, Any] = {0xC0: None, 0xC2: False, 0xC3: True}
    if b in simple:
        return simple[b]
    fixed = {
        0xCA: ">f",
        0xCB: ">d",
        0xCC: ">B",
        0xCD: ">H",
        0xCE: ">I",
        0xCF: ">Q",
        0xD0: ">b",
        0xD1: ">h",
        0xD2: ">i",
        0xD3: ">q",
    }
    if b in fixed:
        return reader.unpack(fixed[b])
    lengths = {0xC4: ">B", 0xC5: ">H", 0xC6: ">I"}  # bin 8/16/32
    if b in lengths:
        return reader.take(reader.unpack(lengths[b]))
    lengths = {0xD9: ">B", 0xDA: ">H", 0xDB: ">I"}  # str 8/16/32
    if b in lengths:
        return _str(reader, reader.unpack(lengths[b]))
    if b in (0xDC, 0xDD):  # array 16/32
        count = reader.unpack(">H" if b == 0xDC else ">I")
        return [_decode(reader, depth + 1) for _ in range(count)]
    if b in (0xDE, 0xDF):  # map 16/32
        return _map(reader, reader.unpack(">H" if b == 0xDE else ">I"), depth)
    fixext = {0xD4: 1, 0xD5: 2, 0xD6: 4, 0xD7: 8, 0xD8: 16}
    if b in fixext:
        return _ext(reader, fixext[b])
    lengths = {0xC7: ">B", 0xC8: ">H", 0xC9: ">I"}  # ext 8/16/32
    if b in lengths:
        return _ext(reader, reader.unpack(lengths[b]))
    raise MsgpackError(f"invalid MessagePack type byte 0x{b:02x}")  # 0xC1 is never used


def _map(reader: _Reader, count: int, depth: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for _ in range(count):
        key = _decode(reader, depth + 1)
        if isinstance(key, bytes):
            key = key.decode("utf-8", errors="replace")
        elif not isinstance(key, str):
            key = str(key)
        out[key] = _decode(reader, depth + 1)
    return out


def unpackb(data: bytes) -> Any:
    """Decode exactly one MessagePack value; trailing bytes are an error."""
    reader = _Reader(data)
    value = _decode(reader, 0)
    if reader.pos != len(data):
        raise MsgpackError("trailing bytes after MessagePack value")
    return value
