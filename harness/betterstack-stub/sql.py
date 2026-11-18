"""A small ClickHouse SQL subset for the Better Stack query stub (standard library only).

Supported (the shapes shown in Better Stack's "Connect remotely" docs plus what SDK search needs):

    SELECT <* | expr [AS alias], ...>
    FROM remote(<table>) | s3Cluster(<cluster>, <table>[, sampling = x]) | (<select> UNION ALL <select> ...)
    [WHERE <boolean expression>]
    [ORDER BY expr [ASC|DESC], ...]
    [LIMIT n [OFFSET m] | LIMIT m, n]
    [SETTINGS name = value, ...]
    [FORMAT JSONEachRow | JSON | JSONCompact | TabSeparated | TSV | CSV]

Expressions: column names, aliases, string/number literals, NULL, ``=, !=, <>, <, <=, >, >=``,
``[NOT] LIKE``, ``[NOT] ILIKE``, ``[NOT] BETWEEN … AND …``, ``[NOT] IN (…)``, ``IS [NOT] NULL``,
``AND``/``OR``/``NOT``, ``+``/``-`` with ``INTERVAL n unit``, and the functions ``count``,
``JSONExtract``, ``JSONExtractString``, ``JSONExtractInt``, ``JSONExtractUInt``,
``JSONExtractFloat``, ``JSONExtractBool``, ``JSONExtractRaw``, ``JSONHas``, ``toDateTime``,
``toDateTime64``, ``now``, ``lower``, ``upper``, ``toString``, ``position``,
``positionCaseInsensitive``, ``length``. Anything else raises :class:`SqlError` with a ClickHouse
error code.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

# ClickHouse error codes (src/Common/ErrorCodes.cpp) used by the stub.
UNKNOWN_IDENTIFIER = (47, "UNKNOWN_IDENTIFIER")
NOT_IMPLEMENTED = (48, "NOT_IMPLEMENTED")
UNKNOWN_TABLE = (60, "UNKNOWN_TABLE")
SYNTAX_ERROR = (62, "SYNTAX_ERROR")
UNKNOWN_FORMAT = (73, "UNKNOWN_FORMAT")
UNKNOWN_FUNCTION = (46, "UNKNOWN_FUNCTION")
BAD_ARGUMENTS = (36, "BAD_ARGUMENTS")
TYPE_MISMATCH = (53, "TYPE_MISMATCH")
NUMBER_OF_ARGUMENTS_DOESNT_MATCH = (42, "NUMBER_OF_ARGUMENTS_DOESNT_MATCH")
UNKNOWN_QUERY_PARAMETER = (456, "UNKNOWN_QUERY_PARAMETER")
BAD_QUERY_PARAMETER = (457, "BAD_QUERY_PARAMETER")
VERSION = "24.8.0.0-betterstack-stub"

FORMATS = {
    "jsoneachrow": "JSONEachRow",
    "json": "JSON",
    "jsoncompact": "JSONCompact",
    "tabseparated": "TabSeparated",
    "tsv": "TabSeparated",
    "csv": "CSV",
}


class SqlError(Exception):
    """A query error carrying a ClickHouse error code and name."""

    def __init__(self, code: tuple[int, str], message: str) -> None:
        super().__init__(message)
        self.code, self.name = code
        self.message = message


# --- tokenizer -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    kind: str  # ident | qident | string | number | op | lit (bound parameter) | eof
    value: str
    pos: int
    obj: Any = None  # the typed value of a bound parameter


_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+|--[^\n]*|/\*.*?\*/)
  | (?P<number>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*|`(?:[^`\\]|\\.)*`|"(?:[^"\\]|\\.)*")
  | (?P<string>'(?:[^'\\]|\\.|'')*')
  | (?P<param>\{\s*[A-Za-z_][A-Za-z0-9_]*\s*:\s*[^{}]+\})
  | (?P<op><=|>=|!=|<>|==|[=<>(),*.;+\-])
    """,
    re.VERBOSE | re.DOTALL,
)

_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\0",
    "b": "\b",
    "f": "\f",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "`": "`",
}


def _unescape(body: str) -> str:
    out = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            out.append(_ESCAPES.get(body[i + 1], body[i + 1]))
            i += 2
        elif ch == "'" and body[i : i + 2] == "''":
            out.append("'")
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


_INT_RE = re.compile(r"[+-]?\d+")
_FLOAT_RE = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?|[+-]?(inf|nan)", re.IGNORECASE)


def bind_parameter(name: str, type_name: str, raw: str, pos: int) -> Token:
    """ClickHouse query parameter binding: ``{name:Type}`` + HTTP ``param_<name>=raw``."""
    type_name = type_name.strip()
    nullable = type_name.lower().startswith("nullable(") and type_name.endswith(")")
    base = type_name[9:-1].strip() if nullable else type_name
    lower = base.lower()

    def bad() -> SqlError:
        return SqlError(
            BAD_QUERY_PARAMETER, f"Value {raw!r} cannot be parsed as {type_name} for query parameter '{name}'"
        )

    if nullable and raw == "\\N":
        return Token("lit", "NULL", pos, None)
    if lower == "identifier":
        return Token("qident", raw, pos)
    if lower in ("string", "uuid") or lower.startswith(("fixedstring(", "lowcardinality(", "enum")):
        return Token("lit", raw, pos, raw)
    if re.fullmatch(r"u?int(8|16|32|64|128|256)", lower):
        if not _INT_RE.fullmatch(raw) or (lower.startswith("u") and raw.startswith("-")):
            raise bad()
        return Token("lit", raw, pos, int(raw))
    if re.fullmatch(r"float(32|64)|decimal.*", lower):
        if not _FLOAT_RE.fullmatch(raw):
            raise bad()
        return Token("lit", raw, pos, float(raw))
    if lower in ("bool", "boolean"):
        if raw.lower() not in ("true", "false", "1", "0"):
            raise bad()
        return Token("lit", raw, pos, raw.lower() in ("true", "1"))
    if lower in ("date", "date32", "datetime") or lower.startswith(("datetime(", "datetime64")):
        try:
            return Token("lit", raw, pos, parse_datetime(raw))
        except SqlError as exc:
            raise bad() from exc
    raise SqlError(BAD_QUERY_PARAMETER, f"betterstack-stub: unsupported query parameter type {type_name}")


def tokenize(sql: str, params: dict[str, str] | None = None) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    while pos < len(sql):
        match = _TOKEN_RE.match(sql, pos)
        if not match:
            raise SqlError(
                SYNTAX_ERROR, f"Syntax error at position {pos}: unexpected {sql[pos : pos + 20]!r}"
            )
        kind = match.lastgroup or ""
        text = match.group(kind)
        if kind == "ident" and text[0] in '`"':
            tokens.append(Token("qident", _unescape(text[1:-1]), pos))
        elif kind == "string":
            tokens.append(Token("string", _unescape(text[1:-1]), pos))
        elif kind == "param":
            name, _, type_name = text[1:-1].partition(":")
            name = name.strip()
            if params is None or name not in params:
                raise SqlError(UNKNOWN_QUERY_PARAMETER, f"Substitution `{name}` is not set")
            tokens.append(bind_parameter(name, type_name, params[name], pos))
        elif kind != "ws":
            tokens.append(Token(kind, text, pos))
        pos = match.end()
    tokens.append(Token("eof", "", len(sql)))
    return tokens


# --- AST ---------------------------------------------------------------------------------------------


@dataclass
class Expr:
    kind: str  # col | lit | func | binop | unop | interval | star
    value: Any = None
    args: list[Expr] = field(default_factory=list)
    text: str = ""  # ClickHouse-style column name when no alias is given


@dataclass
class SelectItem:
    expr: Expr
    alias: str | None


@dataclass
class Source:
    kind: str  # remote | s3 | union | one (no FROM)
    table: str = ""
    selects: list[Select] = field(default_factory=list)


@dataclass
class Select:
    items: list[SelectItem]
    source: Source
    where: Expr | None = None
    order: list[tuple[Expr, bool]] = field(default_factory=list)  # (expr, descending)
    limit: int | None = None
    offset: int = 0


@dataclass
class Query:
    select: Select
    settings: dict[str, Any]
    format: str | None


KEYWORDS = {
    "select", "from", "where", "order", "by", "limit", "offset", "settings", "format", "union", "all",
    "as", "and", "or", "not", "like", "ilike", "between", "in", "is", "null", "asc", "desc", "interval",
    "group", "having", "join",
}  # fmt: skip


class Parser:
    def __init__(self, sql: str, params: dict[str, str] | None = None) -> None:
        self.tokens = tokenize(sql, params)
        self.i = 0

    # helpers
    @property
    def tok(self) -> Token:
        return self.tokens[self.i]

    def kw(self, *words: str) -> bool:
        return self.tok.kind == "ident" and self.tok.value.lower() in words

    def accept_kw(self, word: str) -> bool:
        if self.kw(word):
            self.i += 1
            return True
        return False

    def expect_kw(self, word: str) -> None:
        if not self.accept_kw(word):
            self.error(f"expected {word.upper()}")

    def op(self, *ops: str) -> bool:
        return self.tok.kind == "op" and self.tok.value in ops

    def accept_op(self, value: str) -> bool:
        if self.op(value):
            self.i += 1
            return True
        return False

    def expect_op(self, value: str) -> None:
        if not self.accept_op(value):
            self.error(f"expected {value!r}")

    def error(self, what: str) -> None:
        got = self.tok.value or "end of query"
        raise SqlError(SYNTAX_ERROR, f"Syntax error at position {self.tok.pos} ({got!r}): {what}")

    def ident(self) -> str:
        if self.tok.kind in ("ident", "qident"):
            value = self.tok.value
            self.i += 1
            return value
        self.error("expected identifier")
        raise AssertionError  # pragma: no cover

    # grammar
    def parse(self) -> Query:
        select = self.select()
        settings: dict[str, Any] = {}
        fmt: str | None = None
        while True:
            if self.accept_kw("settings"):
                while True:
                    name = self.ident().lower()
                    self.expect_op("=")
                    settings[name] = self.literal_value()
                    if not self.accept_op(","):
                        break
            elif self.accept_kw("format"):
                name = self.ident()
                if name.lower() not in FORMATS:
                    raise SqlError(UNKNOWN_FORMAT, f"Unknown output format {name}")
                fmt = FORMATS[name.lower()]
            else:
                break
        self.accept_op(";")
        if self.tok.kind != "eof":
            if self.kw("group", "having", "join"):
                raise SqlError(NOT_IMPLEMENTED, f"betterstack-stub does not support {self.tok.value.upper()}")
            self.error("unexpected token")
        return Query(select, settings, fmt)

    def literal_value(self) -> Any:
        if self.tok.kind == "number":
            text = self.tok.value
            self.i += 1
            return float(text) if any(c in text for c in ".eE") else int(text)
        if self.tok.kind in ("string", "ident"):
            value = self.tok.value
            self.i += 1
            return value
        self.error("expected a setting value")
        raise AssertionError  # pragma: no cover

    def select(self) -> Select:
        self.expect_kw("select")
        items = [self.select_item()]
        while self.accept_op(","):
            items.append(self.select_item())
        source = self.source() if self.accept_kw("from") else Source("one")  # SELECT 1 / version()
        where = self.expr() if self.accept_kw("where") else None
        if self.kw("group", "having", "join"):
            raise SqlError(NOT_IMPLEMENTED, f"betterstack-stub does not support {self.tok.value.upper()}")
        order: list[tuple[Expr, bool]] = []
        if self.accept_kw("order"):
            self.expect_kw("by")
            while True:
                expr = self.expr()
                desc = False
                if self.accept_kw("desc"):
                    desc = True
                else:
                    self.accept_kw("asc")
                order.append((expr, desc))
                if not self.accept_op(","):
                    break
        limit: int | None = None
        offset = 0
        if self.accept_kw("limit"):
            first = self.uint()
            if self.accept_op(","):
                offset, limit = first, self.uint()
            else:
                limit = first
                if self.accept_kw("offset"):
                    offset = self.uint()
        return Select(items, source, where, order, limit, offset)

    def uint(self) -> int:
        if self.tok.kind == "lit" and isinstance(self.tok.obj, int) and not isinstance(self.tok.obj, bool):
            if self.tok.obj < 0:
                self.error("expected an unsigned integer")
            value: int = self.tok.obj
            self.i += 1
            return value
        if self.tok.kind != "number" or not self.tok.value.isdigit():
            self.error("expected an unsigned integer")
        number = int(self.tok.value)
        self.i += 1
        return number

    def select_item(self) -> SelectItem:
        if self.accept_op("*"):
            return SelectItem(Expr("star", text="*"), None)
        expr = self.expr()
        alias = None
        if self.accept_kw("as") or (
            self.tok.kind in ("ident", "qident") and self.tok.value.lower() not in KEYWORDS
        ):
            alias = self.ident()
        return SelectItem(expr, alias)

    def source(self) -> Source:
        if self.accept_op("("):
            selects = [self.select()]
            while self.accept_kw("union"):
                self.expect_kw("all")
                selects.append(self.select())
            self.expect_op(")")
            self.table_alias()
            return Source("union", selects=selects)
        name = self.ident()
        lower = name.lower()
        if lower == "remote":
            self.expect_op("(")
            table = self.ident()
            self.expect_op(")")
            self.table_alias()
            return Source("remote", table=table)
        if lower == "s3cluster":
            self.expect_op("(")
            self.ident()  # cluster name, e.g. primary
            self.expect_op(",")
            table = self.ident()
            while self.accept_op(","):
                self.ident()  # named options like sampling = 0.5
                self.expect_op("=")
                self.literal_value()
            self.expect_op(")")
            self.table_alias()
            return Source("s3", table=table)
        raise SqlError(
            UNKNOWN_TABLE,
            f"Table {name} does not exist; query sources with remote(<source>_logs) "
            "or s3Cluster(primary, <source>_s3)",
        )

    def table_alias(self) -> None:
        """Skip an optional `[AS] alias` after a table source (aliases are not needed by the stub)."""
        if self.accept_kw("as") or (self.tok.kind in ("ident", "qident") and not self.kw(*KEYWORDS)):
            self.ident()

    # expressions: precedence OR < AND < NOT < comparison < additive < primary
    def expr(self) -> Expr:
        left = self.and_expr()
        while self.accept_kw("or"):
            left = Expr("binop", "or", [left, self.and_expr()])
        return left

    def and_expr(self) -> Expr:
        left = self.not_expr()
        while self.accept_kw("and"):
            left = Expr("binop", "and", [left, self.not_expr()])
        return left

    def not_expr(self) -> Expr:
        if self.accept_kw("not"):
            return Expr("unop", "not", [self.not_expr()])
        return self.comparison()

    def comparison(self) -> Expr:
        left = self.additive()
        if self.op("=", "==", "!=", "<>", "<", "<=", ">", ">="):
            op = {"==": "=", "<>": "!="}.get(self.tok.value, self.tok.value)
            self.i += 1
            return Expr("binop", op, [left, self.additive()])
        negate = False
        start = self.i
        if self.accept_kw("not"):
            negate = True
        if self.kw("like", "ilike"):
            op = self.tok.value.lower()
            self.i += 1
            node = Expr("binop", op, [left, self.additive()])
        elif self.accept_kw("between"):
            low = self.additive()
            self.expect_kw("and")
            node = Expr("between", None, [left, low, self.additive()])
        elif self.accept_kw("in"):
            self.expect_op("(")
            values = [self.additive()]
            while self.accept_op(","):
                values.append(self.additive())
            self.expect_op(")")
            node = Expr("in", None, [left, *values])
        elif not negate and self.accept_kw("is"):
            is_not = self.accept_kw("not")
            self.expect_kw("null")
            node = Expr("isnull", None, [left])
            return Expr("unop", "not", [node]) if is_not else node
        else:
            self.i = start
            return left
        return Expr("unop", "not", [node]) if negate else node

    def additive(self) -> Expr:
        left = self.primary()
        while self.op("+", "-"):
            op = self.tok.value
            self.i += 1
            left = Expr("binop", op, [left, self.primary()])
        return left

    def primary(self) -> Expr:
        tok = self.tok
        if self.accept_op("("):
            inner = self.expr()
            self.expect_op(")")
            return inner
        if self.accept_op("-"):
            inner = self.primary()
            return Expr("binop", "-", [Expr("lit", 0), inner])
        if tok.kind == "number":
            self.i += 1
            value = float(tok.value) if any(c in tok.value for c in ".eE") else int(tok.value)
            return Expr("lit", value, text=tok.value)
        if tok.kind == "string":
            self.i += 1
            return Expr("lit", tok.value, text=f"'{tok.value}'")
        if tok.kind == "lit":
            self.i += 1
            return Expr("lit", tok.obj, text=tok.value)
        if self.accept_kw("null"):
            return Expr("lit", None, text="NULL")
        if self.accept_kw("interval"):
            amount = self.primary()
            unit = self.ident().lower().rstrip("s")
            return Expr("interval", unit, [amount])
        if tok.kind in ("ident", "qident"):
            name = self.ident()
            if tok.kind == "ident" and self.accept_op("("):
                args: list[Expr] = []
                if self.accept_op("*"):
                    args.append(Expr("star", text="*"))
                elif not self.op(")"):
                    args.append(self.expr())
                    while self.accept_op(","):
                        args.append(self.expr())
                self.expect_op(")")
                text = "count()" if name.lower() == "count" else f"{name}({', '.join(a.text for a in args)})"
                return Expr("func", name, args, text=text)
            return Expr("col", name, text=name)
        self.error("expected an expression")
        raise AssertionError  # pragma: no cover


def parse(sql: str, params: dict[str, str] | None = None) -> Query:
    return Parser(sql, params).parse()


# --- evaluation --------------------------------------------------------------------------------------

Row = dict[str, Any]
TableResolver = Callable[[str, str], tuple[list[str], list[Row]]]  # (kind, table) -> (columns, rows)

_INTERVAL_UNITS = {
    "second": timedelta(seconds=1),
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
}


def parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return datetime.fromtimestamp(int(text), tz=UTC)
        try:
            parsed = datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", text.replace("Z", "+00:00")))
        except ValueError as exc:
            raise SqlError(TYPE_MISMATCH, f"Cannot parse {value!r} as DateTime") from exc
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise SqlError(TYPE_MISMATCH, f"Cannot convert {type(value).__name__} to DateTime")


def like_regex(pattern: str, insensitive: bool) -> re.Pattern[str]:
    out = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if ch == "%" else "." if ch == "_" else re.escape(ch))
        i += 1
    return re.compile("".join(out), re.DOTALL | (re.IGNORECASE if insensitive else 0))


def _json_path(doc: Any, keys: Sequence[Any]) -> tuple[bool, Any]:
    current = doc
    for key in keys:
        if isinstance(key, int) and not isinstance(key, bool):
            if not isinstance(current, list) or key == 0 or abs(key) > len(current):
                return False, None
            current = current[key - 1] if key > 0 else current[key]
        elif isinstance(current, dict) and str(key) in current:
            current = current[str(key)]
        elif isinstance(current, dict) and "." in str(key):
            # Better Stack docs use dotted keys ('context.hostname') for nested fields.
            found, current = _json_path(current, str(key).split("."))
            if not found:
                return False, None
        else:
            return False, None
    return True, current


def _json_doc(value: Any) -> Any:
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except ValueError:
        return None


def _cast_json(value: Any, found: bool, type_name: str) -> Any:
    type_name = type_name.strip()
    nullable = type_name.lower().startswith("nullable(") and type_name.endswith(")")
    base = type_name[9:-1].strip() if nullable else type_name
    lower = base.lower()
    if not found or value is None:
        if nullable:
            return None
        return "" if lower == "string" else False if lower == "bool" else 0
    if lower == "string":
        return value if isinstance(value, str) else ("" if not nullable else None)
    if lower == "bool":
        return bool(value) if isinstance(value, (bool, int, float)) else (None if nullable else False)
    if re.fullmatch(r"u?int(8|16|32|64|128|256)", lower):
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        return None if nullable else 0
    if re.fullmatch(r"float(32|64)", lower):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return None if nullable else 0.0
    raise SqlError(BAD_ARGUMENTS, f"betterstack-stub: unsupported JSONExtract type {type_name}")


class Evaluator:
    def __init__(self, resolver: TableResolver, now: datetime | None = None) -> None:
        self.resolver = resolver
        self.now = now or datetime.now(tz=UTC)

    # values
    def value(self, expr: Expr, row: Row, aliases: dict[str, Expr]) -> Any:
        kind = expr.kind
        if kind == "lit":
            return expr.value
        if kind == "col":
            if expr.value in row:
                return row[expr.value]
            if expr.value in aliases:
                return self.value(
                    aliases[expr.value], row, {k: v for k, v in aliases.items() if k != expr.value}
                )
            raise SqlError(UNKNOWN_IDENTIFIER, f"Missing columns: '{expr.value}'")
        if kind == "interval":
            if expr.value not in _INTERVAL_UNITS:
                raise SqlError(SYNTAX_ERROR, f"Unsupported INTERVAL unit {expr.value}")
            return _INTERVAL_UNITS[expr.value] * self.value(expr.args[0], row, aliases)
        if kind == "unop":
            return not self.truthy(self.value(expr.args[0], row, aliases))
        if kind == "isnull":
            return self.value(expr.args[0], row, aliases) is None
        if kind == "between":
            left, low, high = (self.value(a, row, aliases) for a in expr.args)
            return self.compare(">=", left, low) and self.compare("<=", left, high)
        if kind == "in":
            left = self.value(expr.args[0], row, aliases)
            return any(self.compare("=", left, self.value(a, row, aliases)) for a in expr.args[1:])
        if kind == "binop":
            op = expr.value
            if op == "and":
                return self.truthy(self.value(expr.args[0], row, aliases)) and self.truthy(
                    self.value(expr.args[1], row, aliases)
                )
            if op == "or":
                return self.truthy(self.value(expr.args[0], row, aliases)) or self.truthy(
                    self.value(expr.args[1], row, aliases)
                )
            left = self.value(expr.args[0], row, aliases)
            right = self.value(expr.args[1], row, aliases)
            if op in ("like", "ilike"):
                if left is None or right is None:
                    return None
                return like_regex(str(right), op == "ilike").fullmatch(self.text(left)) is not None
            if op in ("+", "-"):
                return self.arith(op, left, right)
            return self.compare(op, left, right)
        if kind == "func":
            return self.call(expr, row, aliases)
        raise SqlError(SYNTAX_ERROR, "betterstack-stub: '*' is only allowed in SELECT and count(*)")

    @staticmethod
    def truthy(value: Any) -> bool:
        return bool(value) and value is not None

    @staticmethod
    def text(value: Any) -> str:
        if isinstance(value, datetime):
            return format_datetime(value)
        return value if isinstance(value, str) else json.dumps(value)

    @staticmethod
    def arith(op: str, left: Any, right: Any) -> Any:
        if left is None or right is None:
            return None
        if isinstance(left, datetime) and isinstance(right, timedelta):
            return left + right if op == "+" else left - right
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left + right if op == "+" else left - right
        raise SqlError(TYPE_MISMATCH, f"Illegal types for operator {op}")

    @staticmethod
    def compare(op: str, left: Any, right: Any) -> Any:
        if left is None or right is None:
            return None
        if isinstance(left, datetime) or isinstance(right, datetime):
            left, right = parse_datetime(left), parse_datetime(right)
        elif isinstance(left, str) != isinstance(right, str):
            if isinstance(left, str):
                right = str(right)
            else:
                left = str(left)
        ops: dict[str, Callable[[Any, Any], bool]] = {
            "=": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
        }
        return ops[op](left, right)

    def call(self, expr: Expr, row: Row, aliases: dict[str, Expr]) -> Any:
        name = expr.value.lower()
        if name == "count":
            raise SqlError(
                NOT_IMPLEMENTED, "betterstack-stub: count() is only supported as the whole SELECT list"
            )
        args = [self.value(a, row, aliases) for a in expr.args]

        def arity(*counts: int) -> None:
            if len(args) not in counts:
                raise SqlError(
                    NUMBER_OF_ARGUMENTS_DOESNT_MATCH, f"Wrong number of arguments for {expr.value}"
                )

        if name == "now":
            arity(0)
            return self.now
        if name == "version":
            arity(0)
            return VERSION
        if name in ("todatetime", "todatetime64"):
            arity(1, 2, 3) if name == "todatetime64" else arity(1, 2)
            return parse_datetime(args[0])
        if name in ("lower", "upper"):
            arity(1)
            if args[0] is None:
                return None
            return self.text(args[0]).lower() if name == "lower" else self.text(args[0]).upper()
        if name == "tostring":
            arity(1)
            return None if args[0] is None else self.text(args[0])
        if name == "length":
            arity(1)
            return None if args[0] is None else len(self.text(args[0]).encode())
        if name in ("position", "positioncaseinsensitive"):
            arity(2)
            if args[0] is None or args[1] is None:
                return None
            hay, needle = self.text(args[0]), self.text(args[1])
            if name == "positioncaseinsensitive":
                hay, needle = hay.lower(), needle.lower()
            return hay.find(needle) + 1
        extractors = {
            "jsonextractstring": "String",
            "jsonextractint": "Int64",
            "jsonextractuint": "UInt64",
            "jsonextractfloat": "Float64",
            "jsonextractbool": "Bool",
        }
        if name in extractors or name in ("jsonextract", "jsonextractraw", "jsonhas"):
            if not args:
                raise SqlError(
                    NUMBER_OF_ARGUMENTS_DOESNT_MATCH, f"Wrong number of arguments for {expr.value}"
                )
            keys = args[1:]
            if name == "jsonextract":
                if len(args) < 2 or not isinstance(args[-1], str):
                    raise SqlError(
                        NUMBER_OF_ARGUMENTS_DOESNT_MATCH, "JSONExtract needs a return type as last argument"
                    )
                keys, type_name = args[1:-1], args[-1]
            else:
                type_name = extractors.get(name, "")
            found, value = _json_path(_json_doc(args[0]), keys)
            if name == "jsonhas":
                return found
            if name == "jsonextractraw":
                return json.dumps(value, separators=(",", ":")) if found else ""
            return _cast_json(value, found, type_name)
        raise SqlError(UNKNOWN_FUNCTION, f"Unknown function {expr.value} (not supported by betterstack-stub)")

    # query execution
    def rows(self, source: Source) -> tuple[list[str], list[Row]]:
        if source.kind == "one":
            return [], [{}]
        if source.kind in ("remote", "s3"):
            return self.resolver(source.kind, source.table)
        columns: list[str] = []
        rows: list[Row] = []
        for index, select in enumerate(source.selects):
            names, result = self.run(select)
            if index == 0:
                columns = names
            elif len(names) != len(columns):
                raise SqlError(SYNTAX_ERROR, "UNION ALL parts have a different number of columns")
            rows.extend({columns[i]: r[names[i]] for i in range(len(columns))} for r in result)
        return columns, rows

    def run(self, select: Select) -> tuple[list[str], list[Row]]:
        columns, rows = self.rows(select.source)
        aliases = {item.alias: item.expr for item in select.items if item.alias}
        self._check_identifiers(select, set(columns) | set(aliases))
        if select.where is not None:
            rows = [r for r in rows if self.truthy(self.value(select.where, r, aliases))]
        is_count = [it.expr.kind == "func" and str(it.expr.value).lower() == "count" for it in select.items]
        if any(is_count):
            if not all(is_count):
                raise SqlError(
                    NOT_IMPLEMENTED, "betterstack-stub: count() cannot be mixed with other columns"
                )
            count_names = [it.alias or it.expr.text for it in select.items]
            counted: list[Row] = [dict.fromkeys(count_names, len(rows))]
            return count_names, counted[
                select.offset : None if select.limit is None else select.offset + select.limit
            ]
        for expr, desc in reversed(select.order):

            def key(row: Row, expr: Expr = expr) -> tuple[int, Any]:
                return _sort_key(self.value(expr, row, aliases))

            rows.sort(key=key, reverse=desc)
        end = None if select.limit is None else select.offset + select.limit
        rows = rows[select.offset : end]
        names: list[str] = []
        exprs: list[Expr] = []
        for item in select.items:
            if item.expr.kind == "star":
                names.extend(columns)
                exprs.extend(Expr("col", c, text=c) for c in columns)
            else:
                names.append(item.alias or item.expr.text)
                exprs.append(item.expr)
        return names, [
            {n: self.value(e, r, aliases) for n, e in zip(names, exprs, strict=True)} for r in rows
        ]

    def _check_identifiers(self, select: Select, known: set[str]) -> None:
        def walk(expr: Expr) -> None:
            if expr.kind == "col" and expr.value not in known:
                raise SqlError(UNKNOWN_IDENTIFIER, f"Missing columns: '{expr.value}'")
            for arg in expr.args:
                walk(arg)

        for item in select.items:
            walk(item.expr)
        if select.where is not None:
            walk(select.where)
        for expr, _ in select.order:
            walk(expr)


def _sort_key(value: Any) -> tuple[int, Any]:
    if value is None:
        return (2, 0)  # ClickHouse sorts NULLs last
    if isinstance(value, datetime):
        return (0, value.timestamp())
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (0, value)
    return (1, str(value))


def format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def execute(
    sql: str, resolver: TableResolver, now: datetime | None = None, params: dict[str, str] | None = None
) -> tuple[Query, list[str], list[Row]]:
    query = parse(sql, params)
    names, rows = Evaluator(resolver, now).run(query.select)
    return query, names, rows


# --- output formats ----------------------------------------------------------------------------------


def _json_value(value: Any, quote_ints: bool) -> Any:
    if isinstance(value, datetime):
        return format_datetime(value)
    if isinstance(value, timedelta):
        return int(value.total_seconds())
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and quote_ints:
        return str(value)  # ClickHouse quotes (U)Int64 in JSON formats by default
    return value


def _tsv_value(value: Any) -> str:
    if value is None:
        return "\\N"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return format_datetime(value)
    text = str(value)
    return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def _csv_value(value: Any) -> str:
    if value is None:
        return "\\N"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = format_datetime(value) if isinstance(value, datetime) else str(value)
    return '"' + text.replace('"', '""') + '"'


def _ch_type(values: Iterable[Any]) -> str:
    kinds = {type(v) for v in values if v is not None}
    if kinds == {datetime}:
        return "DateTime64(6)"
    if kinds == {bool}:
        return "Bool"
    if kinds == {int}:
        return "UInt64"
    if kinds and kinds <= {int, float}:
        return "Float64"
    return "String"


def render(fmt: str, names: list[str], rows: list[Row], settings: dict[str, Any]) -> tuple[str, bytes]:
    """Return (content type, body) for a result in a ClickHouse output format."""
    quote = str(settings.get("output_format_json_quote_64bit_integers", 1)) not in ("0", "false")
    if fmt == "JSONEachRow":
        lines = [
            json.dumps(
                {n: _json_value(r[n], quote) for n in names}, separators=(",", ":"), ensure_ascii=False
            )
            for r in rows
        ]
        if str(settings.get("output_format_json_array_of_rows", 0)) in ("1", "true"):
            body = "[\n" + ",\n".join(lines) + ("\n" if lines else "") + "]\n"
        else:
            body = "".join(line + "\n" for line in lines)
        return "application/x-ndjson; charset=UTF-8", body.encode()
    if fmt in ("JSON", "JSONCompact"):
        meta = [{"name": n, "type": _ch_type(r[n] for r in rows)} for n in names]
        if fmt == "JSON":
            data: list[Any] = [{n: _json_value(r[n], quote) for n in names} for r in rows]
        else:
            data = [[_json_value(r[n], quote) for n in names] for r in rows]
        doc = {
            "meta": meta,
            "data": data,
            "rows": len(rows),
            "statistics": {"elapsed": 0.0, "rows_read": len(rows)},
        }
        return "application/json; charset=UTF-8", (
            json.dumps(doc, ensure_ascii=False, indent="\t") + "\n"
        ).encode()
    if fmt == "CSV":
        body = "".join(",".join(_csv_value(r[n]) for n in names) + "\n" for r in rows)
        return "text/csv; charset=UTF-8; header=absent", body.encode()
    body = "".join("\t".join(_tsv_value(r[n]) for n in names) + "\n" for r in rows)
    return "text/tab-separated-values; charset=UTF-8", body.encode()
