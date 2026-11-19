"""Keep regions (``@sdk-kit:keep`` / ``@sdk-kit:endkeep``): parser, render, sync, check and CLI."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from sdk_kit import keep
from sdk_kit.check import check
from sdk_kit.cli import main
from sdk_kit.generate import MANIFEST, content_sha256, new, sync
from sdk_kit.kit import Kit
from sdk_kit.render import RenderError, apply_blocks, render
from sdk_kit.services import Service
from tests.conftest import HEADER, STUB_SERVICES, write

ALPHA = Service.from_dict(STUB_SERVICES[0])

DOC = (
    f"<!-- {HEADER} -->\n"
    "# Configuration of __DISPLAY__\n"
    "\n"
    "<!-- @sdk-kit:keep service-settings (service-owned) -->\n"
    "| `token` | GROW___KEY_UPPER___TOKEN |\n"
    "<!-- @sdk-kit:endkeep -->\n"
    "\n"
    "## Common\n"
    "common text v1\n"
    "<!-- @sdk-kit:keep extra -->\n"
    "<!-- @sdk-kit:endkeep -->\n"
)


def manifest_entry(dest: Path, path: str) -> dict[str, object]:
    data = json.loads((dest / MANIFEST).read_text(encoding="utf-8"))
    return next(e for e in data["generatedFiles"] if e["path"] == path)


@pytest.fixture
def doc_kit(kit: Kit) -> Kit:
    write(kit.template / "common" / "docs" / "configuration.md", DOC)
    return kit


# --------------------------------------------------------------------------- parser


def test_parse_finds_regions_in_every_comment_style() -> None:
    text = (
        "a\n# @sdk-kit:keep one\nx\n# @sdk-kit:endkeep\n"
        "// @sdk-kit:keep two description here\n// @sdk-kit:endkeep\n"
        "/* @sdk-kit:keep three */\ny\nz\n/* @sdk-kit:endkeep */\n"
        "-- @sdk-kit:keep four.v2\n-- @sdk-kit:endkeep\n"
        "  <!-- @sdk-kit:keep five_x -->\r\n  <!-- @sdk-kit:endkeep -->\r\n"
    )
    regions = keep.parse(text)
    assert [(r.name, r.start, r.end) for r in regions] == [
        ("one", 1, 3),
        ("two", 4, 5),
        ("three", 6, 9),
        ("four.v2", 10, 11),
        ("five_x", 12, 13),
    ]
    assert keep.bodies(text) == {"one": "x\n", "two": "", "three": "y\nz\n", "four.v2": "", "five_x": ""}
    assert keep.parse("no markers\n") == []
    assert keep.is_keep_marker("<!-- @sdk-kit:keep a -->\n")
    assert not keep.is_keep_marker("<!-- @sdk-kit:if logging -->")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "# @sdk-kit:keep a\n# @sdk-kit:keep b\n# @sdk-kit:endkeep\n",
            "x:2: @sdk-kit:keep b inside the region 'a'",
        ),
        ("# @sdk-kit:keep a\nbody\n", "x:1: keep region 'a' is never closed"),
        ("# @sdk-kit:endkeep\n", "x:1: @sdk-kit:endkeep without @sdk-kit:keep"),
        (
            "# @sdk-kit:keep a\n# @sdk-kit:endkeep\n# @sdk-kit:keep a\n# @sdk-kit:endkeep\n",
            "x:3: duplicate keep region 'a' (first on line 1)",
        ),
        ("# @sdk-kit:keep\n# @sdk-kit:endkeep\n", "x:1: malformed keep marker"),
        ("# @sdk-kit:keep -bad\n", "x:1: malformed keep marker"),
    ],
)
def test_parse_errors(text: str, message: str) -> None:
    with pytest.raises(keep.KeepError, match=message.replace("(", r"\(").replace(")", r"\)")):
        keep.parse(text, "x")


def test_marker_words_outside_comments_are_text() -> None:
    assert keep.parse('echo "@sdk-kit:keep is a marker"\n') == []


def test_strip_removes_bodies_only() -> None:
    text = "a\n# @sdk-kit:keep r\nbody 1\nbody 2\n# @sdk-kit:endkeep\nb\n"
    assert keep.strip(text) == "a\n# @sdk-kit:keep r\n# @sdk-kit:endkeep\nb\n"
    assert keep.strip("plain\n") == "plain\n"
    malformed = "# @sdk-kit:keep r\nbody\n"
    assert keep.strip(malformed) == malformed
    assert keep.strip_bytes(text.encode()) == keep.strip(text).encode()
    assert keep.strip_bytes(b"\0binary @sdk-kit:keep") == b"\0binary @sdk-kit:keep"
    assert keep.strip_bytes(b"\xff\xfe @sdk-kit:keep") == b"\xff\xfe @sdk-kit:keep"
    assert keep.strip_bytes(b"no markers") == b"no markers"


def test_merge_keeps_existing_bodies_and_template_defaults() -> None:
    end = "# @sdk-kit:endkeep\n"
    rendered = f"v2\n# @sdk-kit:keep a new desc\ndefault a\n{end}# @sdk-kit:keep b\ndefault b\n{end}"
    existing = (
        f"v1\n# @sdk-kit:keep a\nmine\n{end}# @sdk-kit:keep gone\nold\n{end}# @sdk-kit:keep empty\n\n{end}"
    )
    merged = keep.merge(rendered, existing)
    assert merged.text == (f"v2\n# @sdk-kit:keep a new desc\nmine\n{end}# @sdk-kit:keep b\ndefault b\n{end}")
    assert merged.kept == ("a",)
    assert merged.dropped == ("gone",)  # "empty" holds only whitespace: nothing is lost
    # Malformed existing markers contribute nothing; no regions in the template: text unchanged.
    assert keep.merge(rendered, "# @sdk-kit:keep a\nx\n").kept == ()
    assert keep.merge("plain\n", existing).text == "plain\n"


# --------------------------------------------------------------------------- render


def test_render_keeps_markers_and_checks_them(doc_kit: Kit) -> None:
    files = render(doc_kit, ALPHA)
    text = files["docs/configuration.md"].data.decode()
    assert "<!-- @sdk-kit:keep service-settings (service-owned) -->" in text
    assert "GROW_ALPHA_SECRETS_TOKEN" in text
    assert files["docs/configuration.md"].generated


def test_apply_blocks_keep_inside_if_block() -> None:
    text = "# @sdk-kit:if logging\n# @sdk-kit:keep log\nx\n# @sdk-kit:endkeep\n# @sdk-kit:endif\n"
    assert apply_blocks(text, ("logging",)) == "# @sdk-kit:keep log\nx\n# @sdk-kit:endkeep\n"
    assert apply_blocks(text, ("secrets",)) == ""


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("# @sdk-kit:keep a\n# @sdk-kit:keep b\n# @sdk-kit:endkeep\n# @sdk-kit:endkeep\n", "do not nest"),
        ("# @sdk-kit:keep a\n", "never closed"),
        # A region cut in half by a category block is only visible after rendering.
        (
            "# @sdk-kit:keep a\n# @sdk-kit:if logging\n# @sdk-kit:endkeep\n# @sdk-kit:endif\n",
            r"\(rendered\):1: keep region 'a' is never closed",
        ),
    ],
)
def test_render_rejects_malformed_keep_markers(text: str, message: str) -> None:
    with pytest.raises(RenderError, match=message):
        apply_blocks(text, ("secrets",), "tpl/file.md")


# --------------------------------------------------------------------------- sync


def test_new_records_hash_without_region_bodies(doc_kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(doc_kit, ALPHA, dest)
    data = (dest / "docs" / "configuration.md").read_bytes()
    entry = manifest_entry(dest, "docs/configuration.md")
    assert entry["sha256"] == content_sha256(data) != hashlib.sha256(data).hexdigest()
    # Files without regions keep the plain SHA-256 (manifests of older sdk-kit versions stay valid).
    readme = manifest_entry(dest, "docs/secrets.md")
    assert readme["sha256"] == hashlib.sha256((dest / "docs" / "secrets.md").read_bytes()).hexdigest()


def test_sync_keeps_service_region_and_updates_the_rest(doc_kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(doc_kit, ALPHA, dest)
    target = dest / "docs" / "configuration.md"
    text = target.read_text().replace("| `token` | GROW_ALPHA_SECRETS_TOKEN |\n", "| `role` | ALPHA_ROLE |\n")
    target.write_text(
        text.replace("<!-- @sdk-kit:keep extra -->\n", "<!-- @sdk-kit:keep extra -->\n## Alpha notes\n")
    )
    # A service edit inside a region is not a local modification.
    unchanged = sync(doc_kit, dest)
    assert "docs/configuration.md" in unchanged.unchanged and not unchanged.conflicts
    tpl = doc_kit.template / "common" / "docs" / "configuration.md"
    tpl.write_text(tpl.read_text().replace("common text v1", "common text v2"))
    report = sync(doc_kit, dest)
    assert report.updated == ["docs/configuration.md"]
    result = target.read_text()
    assert "common text v2" in result and "| `role` | ALPHA_ROLE |" in result and "## Alpha notes" in result
    assert "GROW_ALPHA_SECRETS_TOKEN" not in result
    assert manifest_entry(dest, "docs/configuration.md")["sha256"] == content_sha256(target.read_bytes())
    # An edit outside the regions is still a local modification.
    target.write_text(result.replace("## Common", "## Common (local)"))
    tpl.write_text(tpl.read_text().replace("common text v2", "common text v3"))
    blocked = sync(doc_kit, dest)
    assert blocked.modified == ["docs/configuration.md"] and blocked.conflicts


def test_sync_adds_regions_to_a_pristine_file_without_markers(doc_kit: Kit, tmp_path: Path) -> None:
    """Upgrade path: a repo generated before the template had regions gets the template defaults."""
    tpl = doc_kit.template / "common" / "docs" / "configuration.md"
    tpl.write_text(f"<!-- {HEADER} -->\n# old\n| `token` | x |\n")
    dest = tmp_path / "alpha"
    new(doc_kit, ALPHA, dest)
    tpl.write_text(DOC)
    report = sync(doc_kit, dest)
    assert report.updated == ["docs/configuration.md"]
    assert "@sdk-kit:keep service-settings" in (dest / "docs" / "configuration.md").read_text()


def test_sync_never_clobbers_a_modified_file_without_markers(doc_kit: Kit, tmp_path: Path) -> None:
    tpl = doc_kit.template / "common" / "docs" / "configuration.md"
    tpl.write_text(f"<!-- {HEADER} -->\n# old\n")
    dest = tmp_path / "alpha"
    new(doc_kit, ALPHA, dest)
    target = dest / "docs" / "configuration.md"
    target.write_text(target.read_text() + "service notes\n")
    tpl.write_text(DOC)
    report = sync(doc_kit, dest)
    assert report.modified == ["docs/configuration.md"]
    assert target.read_text().endswith("service notes\n")


def test_sync_region_removed_by_template_is_a_conflict(doc_kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(doc_kit, ALPHA, dest)
    target = dest / "docs" / "configuration.md"
    target.write_text(
        target.read_text().replace("<!-- @sdk-kit:keep extra -->\n", "<!-- @sdk-kit:keep extra -->\nmine\n")
    )
    tpl = doc_kit.template / "common" / "docs" / "configuration.md"
    tpl.write_text(tpl.read_text().replace("<!-- @sdk-kit:keep extra -->\n<!-- @sdk-kit:endkeep -->\n", ""))
    report = sync(doc_kit, dest)
    assert report.dropped == ["docs/configuration.md [extra]"] and report.conflicts
    assert "mine" in target.read_text()
    forced = sync(doc_kit, dest, force=True)
    assert forced.updated == ["docs/configuration.md"]
    assert "mine" not in target.read_text()


def test_sync_empty_region_removed_by_template_updates(doc_kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(doc_kit, ALPHA, dest)
    tpl = doc_kit.template / "common" / "docs" / "configuration.md"
    tpl.write_text(tpl.read_text().replace("<!-- @sdk-kit:keep extra -->\n<!-- @sdk-kit:endkeep -->\n", ""))
    assert sync(doc_kit, dest).updated == ["docs/configuration.md"]


def test_sync_stale_file_with_region_content_is_kept(doc_kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(doc_kit, ALPHA, dest)
    target = dest / "docs" / "configuration.md"
    target.write_text(
        target.read_text().replace("<!-- @sdk-kit:keep extra -->\n", "<!-- @sdk-kit:keep extra -->\nmine\n")
    )
    (doc_kit.template / "common" / "docs" / "configuration.md").unlink()
    report = sync(doc_kit, dest)
    # Defaults count as content too: sdk-kit no longer knows them for a file it stopped rendering.
    assert report.dropped == ["docs/configuration.md [service-settings, extra]"] and target.exists()
    assert sync(doc_kit, dest, force=True).removed == ["docs/configuration.md"]
    assert not target.exists()


def test_sync_stale_file_with_empty_regions_is_removed(doc_kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(doc_kit, ALPHA, dest)
    target = dest / "docs" / "configuration.md"
    text = target.read_text().replace("| `token` | GROW_ALPHA_SECRETS_TOKEN |\n", "")
    target.write_text(text)
    (doc_kit.template / "common" / "docs" / "configuration.md").unlink()
    assert sync(doc_kit, dest).removed == ["docs/configuration.md"]


# --------------------------------------------------------------------------- check and CLI


def test_check_reports_broken_keep_markers(doc_kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha-secrets"
    new(doc_kit, ALPHA, dest)
    assert check(dest) == []
    target = dest / "docs" / "configuration.md"
    target.write_text(target.read_text().replace("<!-- @sdk-kit:endkeep -->\n", "", 1))
    problems = check(dest)
    assert any(p.startswith("docs/configuration.md:") and "do not nest" in p for p in problems), problems
    # A service-owned file (header removed) is not checked.
    target.write_text(target.read_text().replace(f"<!-- {HEADER.replace('__SDK_KIT_VERSION__', '')}", "x"))
    target.write_text(
        "\n".join(line for line in target.read_text().splitlines() if "Generated by" not in line)
    )
    assert check(dest) == []


def test_cli_sync_reports_dropped_region(doc_kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(doc_kit, ALPHA, dest)
    target = dest / "docs" / "configuration.md"
    target.write_text(
        target.read_text().replace("<!-- @sdk-kit:keep extra -->\n", "<!-- @sdk-kit:keep extra -->\nmine\n")
    )
    tpl = doc_kit.template / "common" / "docs" / "configuration.md"
    tpl.write_text(tpl.read_text().replace("<!-- @sdk-kit:keep extra -->\n<!-- @sdk-kit:endkeep -->\n", ""))
    out = io.StringIO()
    code = main(["--kit", str(doc_kit.root), "sync", "--dest", str(dest)], out=out)
    assert code == 1
    assert (
        "SKIPPED (keep region with content no longer in the template; --force drops it): "
        "docs/configuration.md [extra]" in out.getvalue()
    )
    assert "1 skipped" in out.getvalue()


def test_sync_force_removes_stale_file_with_broken_markers(doc_kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(doc_kit, ALPHA, dest)
    target = dest / "docs" / "configuration.md"
    target.write_text(target.read_text().replace("<!-- @sdk-kit:endkeep -->\n", "", 1))
    (doc_kit.template / "common" / "docs" / "configuration.md").unlink()
    assert sync(doc_kit, dest).modified == ["docs/configuration.md"]
    assert sync(doc_kit, dest, force=True).removed == ["docs/configuration.md"]
