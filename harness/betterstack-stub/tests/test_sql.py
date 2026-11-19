from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sql

NOW = datetime(2026, 11, 18, 12, 0, 0, tzinfo=UTC)
LOGS = [
    {"dt": NOW - timedelta(minutes=3), "raw": json.dumps({"message": "alpha run1", "level": "INFO", "n": 1})},
    {"dt": NOW - timedelta(minutes=2), "raw": json.dumps({"message": "beta RUN1", "level": "ERROR", "n": 2,
                                                          "context": {"hostname": "h1"},
                                                          "tags": ["a", "b"]})},
    {"dt": NOW - timedelta(minutes=1), "raw": json.dumps({"message": "gamma run2", "level": "INFO",
                                                          "ok": True, "f": 1.5, "s": "7"})},
]  # fmt: skip


def resolver(kind: str, table: str) -> tuple[list[str], list[dict[str, Any]]]:
    if kind == "remote" and table == "t1_src_logs":
        return ["dt", "raw"], [dict(r) for r in LOGS]
    if kind == "s3" and table == "t1_src_s3":
        return ["dt", "raw", "_row_type"], []
    raise sql.SqlError(sql.UNKNOWN_TABLE, f"Table {table} does not exist")


def run(query: str) -> list[dict[str, Any]]:
    return sql.execute(query, resolver, now=NOW)[2]


def messages(rows: list[dict[str, Any]]) -> list[str]:
    return [json.loads(r["raw"])["message"] for r in rows]


def test_documented_search_query() -> None:
    rows = run(
        """SELECT dt, raw
        FROM (
          SELECT dt, raw FROM remote(t1_src_logs)
          UNION ALL
          SELECT dt, raw FROM s3Cluster(primary, t1_src_s3) WHERE _row_type = 1
        )
        WHERE raw LIKE '%run1%'
        ORDER BY dt ASC
        LIMIT 5000
        FORMAT JSONEachRow"""
    )
    assert messages(rows) == ["alpha run1"]


def test_ilike_not_like_order_limit_offset() -> None:
    assert messages(run("SELECT raw FROM remote(t1_src_logs) WHERE raw ILIKE '%run1%' ORDER BY dt DESC")) == [
        "beta RUN1",
        "alpha run1",
    ]
    assert messages(run("SELECT raw FROM remote(t1_src_logs) WHERE raw NOT LIKE '%run1%'")) == [
        "beta RUN1",
        "gamma run2",
    ]
    assert messages(run("SELECT raw FROM remote(t1_src_logs) WHERE raw NOT ILIKE '%run1%'")) == ["gamma run2"]
    assert messages(run("SELECT raw FROM remote(t1_src_logs) ORDER BY dt DESC LIMIT 1 OFFSET 1")) == [
        "beta RUN1"
    ]
    assert messages(run("SELECT raw FROM remote(t1_src_logs) ORDER BY dt LIMIT 1, 2")) == [
        "beta RUN1",
        "gamma run2",
    ]


def test_like_escapes_and_underscore() -> None:
    assert sql.like_regex("a\\%b_", False).fullmatch("a%bc")
    assert not sql.like_regex("a\\%b_", False).fullmatch("axbc")
    assert sql.like_regex("A%", True).fullmatch("abc")


def test_json_extract_aliases_and_where_on_alias() -> None:
    rows = run(
        "SELECT dt, JSONExtract(raw, 'level', 'Nullable(String)') AS severity, "
        "JSONExtract(raw, 'context.hostname', 'Nullable(String)') as hostname, "
        "JSONExtract(raw, 'context', 'hostname', 'String') host2 "
        "FROM remote(t1_src_logs) WHERE severity = 'ERROR' LIMIT 100 FORMAT JSONEachRow"
    )
    assert rows == [{"dt": LOGS[1]["dt"], "severity": "ERROR", "hostname": "h1", "host2": "h1"}]


def test_json_functions() -> None:
    row = run(
        "SELECT JSONExtractString(raw, 'message') m, JSONExtractInt(raw, 'n') n, "
        "JSONExtractUInt(raw, 'n') u, "
        "JSONExtractFloat(raw, 'n') f, JSONExtractBool(raw, 'n') b, JSONExtractRaw(raw, 'tags') r, "
        "JSONHas(raw, 'tags') h, JSONExtractString(raw, 'tags', 1) t1, "
        "JSONExtractString(raw, 'tags', -1) tl, "
        "JSONExtractString(raw, 'tags', 9) t9, JSONExtractRaw(raw, 'nope') rn, JSONHas(raw, 'nope') hn "
        "FROM remote(t1_src_logs) WHERE JSONExtractInt(raw, 'n') = 2"
    )[0]
    assert row == {"m": "beta RUN1", "n": 2, "u": 2, "f": 2.0, "b": True, "r": '["a","b"]', "h": True,
                   "t1": "a", "tl": "b", "t9": "", "rn": "", "hn": False}  # fmt: skip


@pytest.mark.parametrize(
    "type_name,expected",
    [
        ("String", ""),
        ("Nullable(String)", None),
        ("Int64", 0),
        ("Nullable(Int64)", None),
        ("Float64", 0.0),
        ("Bool", False),
    ],
)
def test_json_extract_missing_and_mismatched(type_name: str, expected: Any) -> None:
    rows = run(f"SELECT JSONExtract(raw, 'missing', '{type_name}') v FROM remote(t1_src_logs) LIMIT 1")
    assert rows[0]["v"] == expected


def test_json_extract_casts() -> None:
    row = run(
        "SELECT JSONExtract(raw, 'ok', 'Int64') a, JSONExtract(raw, 's', 'Int64') b, "
        "JSONExtract(raw, 's', 'Nullable(Int64)') c, JSONExtract(raw, 'f', 'Int32') d, "
        "JSONExtract(raw, 'f', 'String') e, JSONExtract(raw, 'f', 'Nullable(String)') g, "
        "JSONExtract(raw, 's', 'Bool') h, JSONExtract(raw, 's', 'Nullable(Bool)') i, "
        "JSONExtract(raw, 's', 'Float32') j, JSONExtract(raw, 's', 'Nullable(Float64)') k, "
        "JSONExtract(raw, 'ok', 'Float64') l, JSONExtract(raw, 'ok', 'Nullable(Float64)') m2 "
        "FROM remote(t1_src_logs) WHERE raw LIKE '%gamma%'"
    )[0]
    assert row == {"a": 1, "b": 0, "c": None, "d": 1, "e": "", "g": None, "h": False, "i": None,
                   "j": 0.0, "k": None, "l": 0.0, "m2": None}  # fmt: skip
    with pytest.raises(sql.SqlError, match="unsupported JSONExtract type"):
        run("SELECT JSONExtract(raw, 'ok', 'Array(String)') FROM remote(t1_src_logs)")
    assert run("SELECT JSONExtractString('not json', 'a') v FROM remote(t1_src_logs) LIMIT 1") == [{"v": ""}]
    assert run("SELECT JSONExtractString(1, 'a') v FROM remote(t1_src_logs) LIMIT 1") == [{"v": ""}]


def test_time_filters() -> None:
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE dt >= now() - INTERVAL 150 SECOND")) == 2
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE dt > now() - INTERVAL 2 MINUTES")) == 1
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE dt < now() + INTERVAL 1 HOUR")) == 3
    lo = int((NOW - timedelta(minutes=2, seconds=30)).timestamp())
    hi = int(NOW.timestamp())
    q = (
        "SELECT raw FROM remote(t1_src_logs) "
        f"WHERE dt BETWEEN toDateTime64({lo}, 0, 'UTC') AND toDateTime64({hi}, 0, 'UTC')"
    )
    assert len(run(q)) == 2
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE dt >= '2026-11-18 11:57:30'")) == 2
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE dt >= toDateTime('2026-11-18T11:57:30Z')")) == 2
    assert (
        len(run("SELECT raw FROM remote(t1_src_logs) WHERE dt NOT BETWEEN '2026-11-18 11:57:30' AND now()"))
        == 1
    )
    assert len(run(f"SELECT raw FROM remote(t1_src_logs) WHERE dt >= '{lo}'")) == 2
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE dt >= now() - INTERVAL 1 DAY")) == 3
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE dt >= now() - INTERVAL 1 WEEK")) == 3


def test_parse_datetime_variants() -> None:
    assert sql.parse_datetime(0) == datetime(1970, 1, 1, tzinfo=UTC)
    assert sql.parse_datetime("2026-11-18 12:00:00.1234567") == datetime(
        2026, 11, 18, 12, 0, 0, 123456, tzinfo=UTC
    )
    assert sql.parse_datetime(NOW) is NOW
    with pytest.raises(sql.SqlError, match="Cannot parse"):
        sql.parse_datetime("yesterday")
    with pytest.raises(sql.SqlError, match="Cannot convert"):
        sql.parse_datetime([1])


def test_boolean_logic_in_null_and_comparisons() -> None:
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE raw LIKE '%alpha%' OR raw LIKE '%gamma%'")) == 2
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE NOT (raw LIKE '%alpha%') AND 1 = 1")) == 2
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE JSONExtractInt(raw, 'n') IN (1, 2)")) == 2
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE JSONExtractInt(raw, 'n') NOT IN (1, 2)")) == 1
    nullable = "JSONExtract(raw, 'context.hostname', 'Nullable(String)')"
    assert len(run(f"SELECT raw FROM remote(t1_src_logs) WHERE {nullable} IS NULL")) == 2
    assert len(run(f"SELECT raw FROM remote(t1_src_logs) WHERE {nullable} IS NOT NULL")) == 1
    assert len(run(f"SELECT raw FROM remote(t1_src_logs) WHERE {nullable} = 'x'")) == 0
    assert len(run(f"SELECT raw FROM remote(t1_src_logs) WHERE {nullable} LIKE '%'")) == 1
    for op, n in (("!=", 2), ("<>", 2), ("<", 1), ("<=", 2), (">", 1), (">=", 2), ("==", 1)):
        assert len(run(f"SELECT raw FROM remote(t1_src_logs) WHERE JSONExtractInt(raw, 'n') {op} 1")) in (
            n,
            3 - n,
        )
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE JSONExtractString(raw, 's') = 7")) == 1
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE 7 = JSONExtractString(raw, 's')")) == 1
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE -1 < 0 AND 1 + 1 = 2 AND 3 - 1 = 2")) == 3
    assert len(run("SELECT raw FROM remote(t1_src_logs) WHERE NULL + 1 IS NULL")) == 3


def test_string_functions() -> None:
    row = run(
        "SELECT lower(JSONExtractString(raw, 'message')) l, upper('ab') u, toString(5) s, length('héllo') n, "
        "position(raw, 'beta') p, positionCaseInsensitive(raw, 'RUN1') pc, toString(dt) ds, lower(NULL) ln, "
        "toString(NULL) tn, length(NULL) lnn, position(NULL, 'a') pn, dt AS d2 "
        "FROM remote(t1_src_logs) WHERE raw LIKE '%beta%'"
    )[0]
    assert row["l"] == "beta run1" and row["u"] == "AB" and row["s"] == "5" and row["n"] == 6
    assert row["p"] > 0 and row["pc"] > 0 and row["ds"] == "2026-11-18 11:58:00.000000"
    assert row["ln"] is None and row["tn"] is None and row["lnn"] is None and row["pn"] is None


def test_star_and_count() -> None:
    rows = run("SELECT * FROM remote(t1_src_logs) ORDER BY dt LIMIT 1")
    assert list(rows[0]) == ["dt", "raw"]
    _, names, rows = sql.execute("SELECT count() FROM remote(t1_src_logs) WHERE raw LIKE '%run%'", resolver)
    assert names == ["count()"] and rows == [{"count()": 2}]
    assert run("SELECT count(*) AS c FROM remote(t1_src_logs)") == [{"c": 3}]
    assert run("SELECT count() FROM remote(t1_src_logs) LIMIT 0") == []


def test_settings_format_comments_quoted_identifiers() -> None:
    query = sql.parse(
        '/* c */ SELECT `raw` FROM remote("t1_src_logs") -- tail\n'
        "SETTINGS output_format_json_array_of_rows = 1, max_result_rows = 10, x = 'y', f = 0.5 FORMAT JSON;"
    )
    assert query.settings == {
        "output_format_json_array_of_rows": 1,
        "max_result_rows": 10,
        "x": "y",
        "f": 0.5,
    }
    assert query.format == "JSON"
    assert sql.parse("SELECT raw FROM remote(t) FORMAT TSV").format == "TabSeparated"
    assert sql.parse("SELECT raw FROM remote(t) AS x FORMAT CSV").format == "CSV"
    assert sql.parse("SELECT raw FROM (SELECT raw FROM remote(t)) sub").select.source.kind == "union"
    assert sql.parse("SELECT 'it''s', 'a\\tb' FROM remote(t)").select.items[0].expr.value == "it's"
    assert sql.parse("SELECT raw FROM s3Cluster(primary, t_s3, sampling = 0.5)").select.source.kind == "s3"


@pytest.mark.parametrize(
    "query,code",
    [
        ("SELEC raw FROM remote(t1_src_logs)", 62),
        ("SELECT raw FROM t1_src_logs", 60),
        ("SELECT raw FROM remote(t9_logs)", 60),
        ("SELECT nope FROM remote(t1_src_logs)", 47),
        ("SELECT raw FROM remote(t1_src_logs) WHERE nope = 1", 47),
        ("SELECT raw FROM remote(t1_src_logs) ORDER BY nope", 47),
        ("SELECT raw FROM remote(t1_src_logs) FORMAT Parquet", 73),
        ("SELECT raw FROM remote(t1_src_logs) GROUP BY raw", 48),
        ("SELECT raw FROM remote(t1_src_logs) WHERE 1 = 1 GROUP BY raw", 48),
        ("SELECT count(), raw FROM remote(t1_src_logs)", 48),
        ("SELECT raw FROM remote(t1_src_logs) WHERE count() > 1", 48),
        ("SELECT foo(raw) FROM remote(t1_src_logs)", 46),
        ("SELECT now(1) FROM remote(t1_src_logs)", 42),
        ("SELECT JSONExtract(raw) FROM remote(t1_src_logs)", 42),
        ("SELECT JSONExtractString() FROM remote(t1_src_logs)", 42),
        ("SELECT raw FROM remote(t1_src_logs) WHERE dt > now() - INTERVAL 1 MONTH", 62),
        ("SELECT raw FROM remote(t1_src_logs) WHERE raw + 1 = 2", 53),
        ("SELECT raw FROM remote(t1_src_logs) WHERE dt > 'nope'", 53),
        ("SELECT raw FROM remote(t1_src_logs) LIMIT x", 62),
        ("SELECT raw FROM remote(t1_src_logs) x extra", 62),
        ("SELECT raw FROM remote(t1_src_logs) WHERE", 62),
        ("SELECT raw FROM remote(t1_src_logs) SETTINGS a = (", 62),
        (
            "SELECT raw FROM (SELECT dt, raw FROM remote(t1_src_logs) "
            "UNION ALL SELECT raw FROM remote(t1_src_logs))",
            62,
        ),
        ("SELECT raw FROM remote(t1_src_logs) WHERE raw IS 1", 62),
        ("SELECT 1 FROM remote(t1_src_logs) WHERE $", 62),
        ("SELECT raw FROM remote(t1_src_logs) WHERE raw = *", 62),
        ("SELECT 1 FROM remote(t1_src_logs) WHERE 1 = (", 62),
    ],
)
def test_errors(query: str, code: int) -> None:
    with pytest.raises(sql.SqlError) as info:
        run(query)
    assert info.value.code == code


def test_star_expression_outside_select_is_rejected() -> None:
    evaluator = sql.Evaluator(resolver)
    with pytest.raises(sql.SqlError, match="only allowed"):
        evaluator.value(sql.Expr("star"), {}, {})


def test_render_formats() -> None:
    names = ["dt", "raw", "n", "f", "b", "none"]
    rows = [{"dt": NOW, "raw": 'a\t"b"\n', "n": 3, "f": 1.5, "b": True, "none": None}]
    ctype, body = sql.render("JSONEachRow", names, rows, {})
    assert ctype.startswith("application/x-ndjson")
    assert json.loads(body) == {"dt": "2026-11-18 12:00:00.000000", "raw": 'a\t"b"\n', "n": "3", "f": 1.5,
                                "b": True, "none": None}  # fmt: skip
    _, body = sql.render("JSONEachRow", names, rows, {"output_format_json_quote_64bit_integers": "0"})
    assert json.loads(body)["n"] == 3
    _, body = sql.render("JSONEachRow", names, rows, {"output_format_json_array_of_rows": 1})
    assert json.loads(body)[0]["n"] == "3"
    _, body = sql.render("JSONEachRow", names, [], {"output_format_json_array_of_rows": "1"})
    assert json.loads(body) == []
    _, body = sql.render("JSON", names, rows, {})
    doc = json.loads(body)
    assert doc["rows"] == 1 and doc["data"][0]["raw"] == 'a\t"b"\n'
    assert [m["type"] for m in doc["meta"]] == [
        "DateTime64(6)",
        "String",
        "UInt64",
        "Float64",
        "Bool",
        "String",
    ]
    _, body = sql.render("JSONCompact", names, rows, {})
    assert json.loads(body)["data"][0][2] == "3"
    _, body = sql.render("TabSeparated", names, rows, {})
    assert body.decode() == '2026-11-18 12:00:00.000000\ta\\t"b"\\n\t3\t1.5\ttrue\t\\N\n'
    _, body = sql.render("CSV", names, rows, {})
    assert body.decode() == '"2026-11-18 12:00:00.000000","a\t""b""\n",3,1.5,true,\\N\n'
    assert sql._json_value(timedelta(seconds=5), True) == 5
    assert sql._tsv_value(False) == "false" and sql._csv_value(False) == "false"


def test_tokenizer_rejects_garbage() -> None:
    with pytest.raises(sql.SqlError, match="unexpected"):
        sql.tokenize("SELECT #")
