"""OTLP/HTTP logs decoding (protobuf wire format and OTLP JSON), standard library only.

Decodes ``ExportLogsServiceRequest`` from opentelemetry-proto (``collector/logs/v1``,
``logs/v1``, ``common/v1``, ``resource/v1``) into flat records:

    {"timeUnixNano": int, "observedTimeUnixNano": int, "severityNumber": int, "severityText": str,
     "body": value, "attributes": {...}, "resource": {...}, "scope": {"name", "version"},
     "traceId": hex, "spanId": hex, "flags": int, "eventName": str}

Unknown fields are skipped, as protobuf requires.
"""

from __future__ import annotations

import base64
import struct
from typing import Any


class OtlpError(ValueError):
    """The payload is not a valid OTLP logs request."""


# --- protobuf wire format ------------------------------------------------------------------------


def _varint(data: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if pos >= len(data):
            raise OtlpError("truncated varint")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise OtlpError("varint too long")


def fields(data: bytes) -> list[tuple[int, int, Any]]:
    """Split a message into (field number, wire type, value); value is int or bytes."""
    out: list[tuple[int, int, Any]] = []
    pos = 0
    while pos < len(data):
        key, pos = _varint(data, pos)
        number, wire = key >> 3, key & 7
        value: Any
        if number == 0:
            raise OtlpError("field number 0")
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire == 1:
            if pos + 8 > len(data):
                raise OtlpError("truncated fixed64")
            value = struct.unpack_from("<Q", data, pos)[0]
            pos += 8
        elif wire == 2:
            length, pos = _varint(data, pos)
            if pos + length > len(data):
                raise OtlpError("truncated length-delimited field")
            value = data[pos : pos + length]
            pos += length
        elif wire == 5:
            if pos + 4 > len(data):
                raise OtlpError("truncated fixed32")
            value = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        else:
            raise OtlpError(f"unsupported wire type {wire}")
        out.append((number, wire, value))
    return out


def _str(value: Any) -> str:
    if not isinstance(value, bytes):
        raise OtlpError("expected a length-delimited string")
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OtlpError("invalid UTF-8 string") from exc


def _sint64(value: int) -> int:
    return value - (1 << 64) if value >= 1 << 63 else value


def any_value(data: bytes) -> Any:
    result: Any = None
    for number, wire, value in fields(data):
        if number == 1 and wire == 2:
            result = _str(value)
        elif number == 2 and wire == 0:
            result = bool(value)
        elif number == 3 and wire == 0:
            result = _sint64(value)
        elif number == 4 and wire == 1:
            result = struct.unpack("<d", struct.pack("<Q", value))[0]
        elif number == 5 and wire == 2:
            result = [any_value(v) for n, w, v in fields(value) if n == 1 and w == 2]
        elif number == 6 and wire == 2:
            result = key_values([v for n, w, v in fields(value) if n == 1 and w == 2])
        elif number == 7 and wire == 2:
            result = base64.b64encode(value).decode("ascii")
    return result


def key_values(items: list[bytes]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items:
        key, value = "", None
        for number, wire, raw in fields(item):
            if number == 1 and wire == 2:
                key = _str(raw)
            elif number == 2 and wire == 2:
                value = any_value(raw)
        out[key] = value
    return out


def _attributes(data: bytes, number: int) -> dict[str, Any]:
    return key_values([v for n, w, v in fields(data) if n == number and w == 2])


def _log_record(data: bytes, resource: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "timeUnixNano": 0,
        "observedTimeUnixNano": 0,
        "severityNumber": 0,
        "severityText": "",
        "body": None,
        "attributes": {},
        "resource": resource,
        "scope": scope,
        "traceId": "",
        "spanId": "",
        "flags": 0,
        "eventName": "",
    }
    attr_items: list[bytes] = []
    for number, wire, value in fields(data):
        if number == 1 and wire == 1:
            rec["timeUnixNano"] = value
        elif number == 11 and wire == 1:
            rec["observedTimeUnixNano"] = value
        elif number == 2 and wire == 0:
            rec["severityNumber"] = value
        elif number == 3 and wire == 2:
            rec["severityText"] = _str(value)
        elif number == 5 and wire == 2:
            rec["body"] = any_value(value)
        elif number == 6 and wire == 2:
            attr_items.append(value)
        elif number == 8 and wire == 5:
            rec["flags"] = value
        elif number == 9 and wire == 2:
            rec["traceId"] = value.hex()
        elif number == 10 and wire == 2:
            rec["spanId"] = value.hex()
        elif number == 12 and wire == 2:
            rec["eventName"] = _str(value)
    rec["attributes"] = key_values(attr_items)
    return rec


def decode_protobuf(data: bytes) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for number, wire, resource_logs in fields(data):
        if number != 1 or wire != 2:
            continue
        resource: dict[str, Any] = {}
        scope_logs: list[bytes] = []
        for n, w, value in fields(resource_logs):
            if n == 1 and w == 2:
                resource = _attributes(value, 1)
            elif n == 2 and w == 2:
                scope_logs.append(value)
        for item in scope_logs:
            scope: dict[str, Any] = {}
            logs: list[bytes] = []
            for n, w, value in fields(item):
                if n == 1 and w == 2:
                    for sn, sw, sv in fields(value):
                        if sn in (1, 2) and sw == 2:
                            scope["name" if sn == 1 else "version"] = _str(sv)
                elif n == 2 and w == 2:
                    logs.append(value)
            records.extend(_log_record(log, resource, scope) for log in logs)
    return records


# --- OTLP JSON --------------------------------------------------------------------------------------


def _json_any(value: Any) -> Any:
    if not isinstance(value, dict):
        return None
    if "stringValue" in value:
        return value["stringValue"]
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "intValue" in value:
        return int(value["intValue"])  # int64 is a JSON string in OTLP JSON
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "arrayValue" in value:
        return [_json_any(v) for v in (value["arrayValue"] or {}).get("values", [])]
    if "kvlistValue" in value:
        return _json_kv((value["kvlistValue"] or {}).get("values", []))
    if "bytesValue" in value:
        return value["bytesValue"]
    return None


def _json_kv(items: Any) -> dict[str, Any]:
    if not isinstance(items, list):
        raise OtlpError("attributes must be a list")
    return {
        str(item.get("key", "")): _json_any(item.get("value")) for item in items if isinstance(item, dict)
    }


def decode_json(doc: Any) -> list[dict[str, Any]]:
    if not isinstance(doc, dict):
        raise OtlpError("OTLP JSON body must be an object")
    records: list[dict[str, Any]] = []
    try:
        for resource_logs in doc.get("resourceLogs") or []:
            resource = _json_kv(((resource_logs.get("resource") or {}).get("attributes")) or [])
            for scope_logs in resource_logs.get("scopeLogs") or []:
                raw_scope = scope_logs.get("scope") or {}
                scope = {k: raw_scope[k] for k in ("name", "version") if k in raw_scope}
                for log in scope_logs.get("logRecords") or []:
                    records.append(
                        {
                            "timeUnixNano": int(log.get("timeUnixNano", 0) or 0),
                            "observedTimeUnixNano": int(log.get("observedTimeUnixNano", 0) or 0),
                            "severityNumber": int(log.get("severityNumber", 0) or 0),
                            "severityText": str(log.get("severityText", "")),
                            "body": _json_any(log.get("body")),
                            "attributes": _json_kv(log.get("attributes") or []),
                            "resource": resource,
                            "scope": scope,
                            "traceId": str(log.get("traceId", "")).lower(),
                            "spanId": str(log.get("spanId", "")).lower(),
                            "flags": int(log.get("flags", 0) or 0),
                            "eventName": str(log.get("eventName", "")),
                        }
                    )
    except (AttributeError, TypeError, ValueError) as exc:
        raise OtlpError(f"invalid OTLP JSON: {exc}") from exc
    return records
