from __future__ import annotations

import struct
from datetime import UTC, datetime

import msgpack_decode as m
import pytest
from conftest import packb


@pytest.mark.parametrize(
    "value",
    [
        None, True, False, 0, 5, 127, 128, 255, 256, 65535, 65536, 2**32, 2**63, -1, -32, -33, -128, -129,
        -32768, -32769, -(2**31), -(2**31) - 1, 1.5, "", "hi", "x" * 40, "y" * 300, "z" * 70000,
        [1, 2, [3]], list(range(20)), {"a": {"b": [1, "c"]}}, {f"k{i}": i for i in range(20)},
    ],
)  # fmt: skip
def test_roundtrip(value: object) -> None:
    assert m.unpackb(packb(value)) == value


def test_other_encodings() -> None:
    assert m.unpackb(b"\xca" + struct.pack(">f", 0.5)) == 0.5
    assert m.unpackb(b"\xc5\x00\x02ab") == b"ab"
    assert m.unpackb(b"\xc6\x00\x00\x00\x01a") == b"a"
    assert m.unpackb(b"\xdd\x00\x00\x00\x01\x01") == [1]
    assert m.unpackb(b"\xdf\x00\x00\x00\x01\xa1a\x01") == {"a": 1}
    # non-string map keys become strings
    assert m.unpackb(b"\x82\x01\x02\xc4\x01k\x03") == {"1": 2, "k": 3}


def test_timestamps() -> None:
    assert m.unpackb(b"\xd6\xff" + struct.pack(">I", 10)) == datetime(1970, 1, 1, 0, 0, 10, tzinfo=UTC)
    when = datetime(2026, 11, 18, 12, 0, 1, 250000, tzinfo=UTC)
    assert m.unpackb(packb(when)) == when
    ts96 = b"\xc7\x0c\xff" + struct.pack(">Iq", 5000, -1)
    assert m.unpackb(ts96) == datetime(1969, 12, 31, 23, 59, 59, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    "data,message",
    [
        (b"", "truncated"),
        (b"\xa5ab", "truncated"),
        (b"\x01\x02", "trailing"),
        (b"\xc1", "invalid MessagePack type byte"),
        (b"\xa2\xff\xfe", "invalid UTF-8"),
        (b"\xd4\x05\x00", "unsupported MessagePack ext type 5"),
        (b"\xc7\x03\xff\x00\x00\x00", "invalid timestamp extension length"),
        (b"\xd7\xff" + struct.pack(">Q", (1_000_000_000 << 34)), "invalid timestamp nanoseconds"),
        (b"\xc7\x0c\xff" + struct.pack(">Iq", 0, 2**62), "timestamp out of range"),
        (b"\x91" * 70 + b"\x01", "nesting too deep"),
    ],
)
def test_errors(data: bytes, message: str) -> None:
    with pytest.raises(m.MsgpackError, match=message):
        m.unpackb(data)
