"""Static check for javac's `-Xlint:dangling-doc-comments` (JDK 23+, an error with -Werror on JDK 25).

A doc comment (`/** ... */`) is dangling when javac does not attach it to a declaration:
  * inside a method/constructor/initializer/lambda body (before statements),
  * not the last doc comment before a declaration,
  * after the annotations/modifiers of the declaration (javac takes the doc comment of the first
    modifier token),
  * before `import`, `}` , `;` or an initializer block, or at the end of a body,
  * before `package` outside package-info.java.

Copied from the sdk-kit Java agent (GRO-1366); used by tests/test_java_doc_comments.py.
Usage: python -m tests.java_doc_comments <dir-or-file>...
(exit 1 and one line per finding when anything is dangling)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DECL_KEYWORDS = {"class", "interface", "enum", "record"}
MODIFIERS = {
    "public",
    "protected",
    "private",
    "static",
    "final",
    "abstract",
    "native",
    "synchronized",
    "transient",
    "volatile",
    "strictfp",
    "default",
    "sealed",
    "non-sealed",
}

TOKEN = re.compile(
    r'''(?P<text>"""(?:\\.|[^\\])*?""")'''
    r"""|(?P<str>"(?:\\.|[^"\\\n])*")"""
    r"""|(?P<chr>'(?:\\.|[^'\\\n])+')"""
    r"|(?P<line>//[^\n]*)"
    r"|(?P<doc>/\*\*(?!/).*?\*/)"
    r"|(?P<block>/\*.*?\*/)"
    r"|(?P<word>[A-Za-z_$][A-Za-z0-9_$]*(?:-sealed)?)"
    r"|(?P<num>[0-9][0-9A-Za-z_.]*)"
    r"|(?P<ws>\s+)"
    r"|(?P<op>->|::|\.\.\.|.)",
    re.S,
)


def tokens(src: str) -> list[tuple[str, str, int]]:
    out: list[tuple[str, str, int]] = []
    line = 1
    for m in TOKEN.finditer(src):
        kind = m.lastgroup or "op"
        text = m.group()
        if kind not in ("ws", "line", "block"):
            out.append((kind, text, line))
        line += text.count("\n")
    return out


def check_source(src: str, name: str) -> list[str]:
    toks = tokens(src)
    findings: list[str] = []
    stack: list[str] = []  # "class" or "block" per open brace; parens counted separately
    paren = 0
    stmt_start = 0  # index in toks of the first token after the last ; { }
    prev_sig: tuple[str, str, int] | None = None
    pending_docs: list[tuple[int, int]] = []  # (tok index, line) since the last significant token
    i = 0
    while i < len(toks):
        kind, text, line = toks[i]
        if kind == "doc":
            pending_docs.append((i, line))
            i += 1
            continue
        if pending_docs:
            context = stack[-1] if stack else "top"
            ok_last = _doc_attaches(toks, i, context, prev_sig, name, paren)
            for n, (_, dline) in enumerate(pending_docs):
                last = n == len(pending_docs) - 1
                if not (last and ok_last):
                    findings.append(f"{name}:{dline}: dangling doc comment")
            pending_docs = []
        if text == "(":
            paren += 1
        elif text == ")":
            paren -= 1
        elif text == "{":
            stack.append(_brace_kind(toks, stmt_start, i, paren))
            stmt_start = i + 1
        elif text == "}":
            if stack:
                stack.pop()
            stmt_start = i + 1
        elif text == ";" and paren == 0:
            stmt_start = i + 1
        prev_sig = toks[i]
        i += 1
    for _, dline in pending_docs:
        findings.append(f"{name}:{dline}: dangling doc comment (end of file)")
    return findings


def _brace_kind(toks: list[tuple[str, str, int]], start: int, brace: int, paren: int) -> str:
    if paren > 0:
        return "block"  # array initializer inside an annotation or call
    depth = 0
    words: list[str] = []
    ops: list[str] = []
    for k in range(start, brace):
        t = toks[k][1]
        if t == "(":
            depth += 1
        elif t == ")":
            depth -= 1
        elif depth == 0:
            (words if toks[k][0] == "word" else ops).append(t)
    if any(w in DECL_KEYWORDS for w in words) and "new" not in words and "=" not in ops:
        return "class"
    # anonymous class body: `new Type<...>(...) {`
    j = brace - 1
    while j >= start and toks[j][0] == "doc":
        j -= 1
    if j >= start and toks[j][1] == ")":
        depth = 0
        while j >= start:
            t = toks[j][1]
            if t == ")":
                depth += 1
            elif t == "(":
                depth -= 1
                if depth == 0:
                    break
            j -= 1
        k = j - 1
        while k >= start and (toks[k][0] == "word" or toks[k][1] in ".<>,?"):
            if toks[k][1] == "new":
                return "class"
            k -= 1
    return "block"


def _skip_annotation(toks: list[tuple[str, str, int]], i: int) -> int:
    i += 2  # '@' Name
    while i + 1 < len(toks) and toks[i][1] == "." and toks[i + 1][0] == "word":
        i += 2
    if i < len(toks) and toks[i][1] == "(":
        depth = 0
        while i < len(toks):
            if toks[i][1] == "(":
                depth += 1
            elif toks[i][1] == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
    return i


def _doc_attaches(toks, i, context, prev_sig, name, paren) -> bool:  # noqa: PLR0917
    if paren > 0:
        return False
    # the doc comment must start the declaration: nothing of it may come before
    if prev_sig is not None and prev_sig[1] not in (";", "{", "}", ","):
        return False
    first = toks[i][1]
    if context == "top":
        if first == "package":
            return Path(name).name == "package-info.java"
        if first in ("import",):
            return False
        if first in {"module", "open"}:
            return True
    if context == "block":
        # only a local class/record/interface/enum declaration takes a doc comment in a body
        j = i
        while j < len(toks) and (toks[j][1] == "@" or toks[j][1] in MODIFIERS):
            j = _skip_annotation(toks, j) if toks[j][1] == "@" else j + 1
        return j < len(toks) and toks[j][1] in DECL_KEYWORDS
    if first in ("}", ";", "{"):
        return False
    j = i
    while j < len(toks) and (toks[j][1] == "@" or toks[j][1] in MODIFIERS):
        if toks[j][1] == "@" and j + 1 < len(toks) and toks[j + 1][1] == "interface":
            return True
        j = _skip_annotation(toks, j) if toks[j][1] == "@" else j + 1
    return not (j < len(toks) and toks[j][1] == "{")  # (static) initializer


def main(argv: list[str]) -> int:
    findings: list[str] = []
    for arg in argv:
        p = Path(arg)
        files = [p] if p.is_file() else sorted(p.rglob("*.java"))
        for f in files:
            if any(part in ("target", "node_modules", ".git") for part in f.parts):
                continue
            findings += check_source(f.read_text(encoding="utf-8"), str(f))
    for line in findings:
        print(line)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
