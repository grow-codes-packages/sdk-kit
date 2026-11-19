"""Guard for javac ``-Xlint:dangling-doc-comments`` (JDK 23+; an error with ``-Werror`` on JDK 25).

CI builds the Java template on JDK 17/21/25; a dangling ``/** ... */`` only fails the JDK 25 leg,
so the rendered Java sources of the demo (all categories) are checked here statically.
"""

from __future__ import annotations

from sdk_kit.kit import Kit
from sdk_kit.render import render
from sdk_kit.services import DEMO
from tests.conftest import REPO_ROOT
from tests.java_doc_comments import check_source, main


def test_rendered_java_has_no_dangling_doc_comments() -> None:
    files = render(Kit(REPO_ROOT), DEMO)
    java = {
        path: item
        for path, item in files.items()
        if path.endswith(".java") and (path.startswith("java/") or path.startswith("examples/java/"))
    }
    assert len(java) > 20  # the guard must actually see the Java template
    findings = [f for path, item in java.items() for f in check_source(item.data.decode("utf-8"), path)]
    assert findings == []


def test_checker_finds_dangling_doc_comments() -> None:
    src = (
        "/** dangling: before the package */\n"
        "package a;\n"
        "/** dangling: before an import */\n"
        "import java.util.List;\n"
        "/** first of two: dangling */\n"
        "/** Attached. */\n"
        "public final class A {\n"
        "  /** Attached. */\n"
        "  @Deprecated\n"
        "  void m() {\n"
        "    /** dangling: in a body */\n"
        "    int x = 1;\n"
        "  }\n"
        "  @Override /** dangling: after an annotation */\n"
        '  public String toString() { return ""; }\n'
        "  /** dangling: initializer */\n"
        "  static {}\n"
        "  /** dangling: end of body */\n"
        "}\n"
    )
    lines = [int(f.split(":")[1]) for f in check_source(src, "A.java")]
    assert lines == [1, 3, 5, 11, 14, 16, 18]
    assert check_source("/** Package docs. */\npackage a;\n", "x/package-info.java") == []
    assert check_source("/** trailing */", "B.java") == ["B.java:1: dangling doc comment (end of file)"]


def test_checker_cli(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    good = tmp_path / "src" / "Good.java"
    good.parent.mkdir()
    good.write_text("/** Docs. */\nfinal class Good {}\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 0
    bad = tmp_path / "Bad.java"
    bad.write_text("class Bad { void m() { /** x */ int y; } }\n", encoding="utf-8")
    assert main([str(bad)]) == 1
    assert "Bad.java:1: dangling doc comment" in capsys.readouterr().out
