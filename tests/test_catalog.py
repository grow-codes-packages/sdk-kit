"""Generate demo and every service of spec/services.json with the real repo-level template."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from sdk_kit.check import LEFTOVER_RE, check
from sdk_kit.generate import new, sync
from sdk_kit.kit import Kit, locate
from sdk_kit.render import render
from sdk_kit.services import CATEGORIES, DEMO, LANGS, Service, load_catalog
from tests.conftest import REPO_ROOT

CATALOG = load_catalog(REPO_ROOT / "spec" / "services.json")
ALL = [*CATALOG, DEMO]
COMMON = REPO_ROOT / "template" / "common"
GROW_BADGE = (
    "[![Grow Codes](https://img.shields.io/badge/Grow%20Codes-grow.codes-2ea44f)](https://grow.codes)"
)


@pytest.mark.parametrize("svc", ALL, ids=[s.key for s in ALL])
def test_generate_every_service(real_kit: Kit, tmp_path: Path, svc: Service) -> None:
    dest = tmp_path / svc.key
    new(real_kit, svc, dest)
    assert check(dest) == []

    readme = (dest / "README.md").read_text(encoding="utf-8")
    assert readme.startswith(f"# Grow Codes SDK for {svc.display}\n")
    assert GROW_BADGE in readme
    for lang in LANGS:
        assert (
            f"https://img.shields.io/endpoint?url=https://grow-codes-packages.github.io/{svc.key}/badges/coverage-{lang}.json"
            in readme
        )
    assert f"npm install @grow-codes/{svc.key}" in readme
    assert f"from grow_{svc.key_snake} import {svc.service}Client" in readme
    assert f"GROW_{svc.key_upper}_URL" in readme
    assert f"`{svc.image}`" in readme
    assert "@sdk-kit" not in readme
    for cat, title in (("secrets", "| Secrets |"), ("logging", "| Logging |"), ("tracing", "| Tracing |")):
        assert (title in readme) == (cat in svc.categories), cat

    notice = (dest / "NOTICE").read_text(encoding="utf-8")
    flat = notice.replace("\n", " ")
    assert f"not affiliated with, endorsed or sponsored by the owner of {svc.display} ({svc.vendor})" in flat
    assert f"{svc.display} is a trademark of its owner ({svc.vendor})" in flat
    assert ".." not in flat
    assert (
        "Grow Codes is not\nresponsible for any damage, data loss, security incident, outage or cost"
        in notice
    )

    skill = dest / "skills" / f"{svc.key}-sdk" / "SKILL.md"
    assert skill.read_text(encoding="utf-8").startswith(f"---\nname: {svc.key}-sdk\n")
    agents = (dest / "AGENTS.md").read_text(encoding="utf-8")
    assert f"Categories: **{','.join(svc.categories)}**" in agents
    assert (dest / "CLAUDE.md").readlink() == Path("AGENTS.md")

    config = json.loads((dest / "release-please-config.json").read_text(encoding="utf-8"))
    assert config["separate-pull-requests"] is False
    assert set(config["packages"]) == set(LANGS)
    go = config["packages"]["go"]
    assert (go["component"], go["tag-separator"], go["include-v-in-tag"]) == ("go", "/", True)
    assert {p["release-type"] for p in config["packages"].values()} == {
        "node",
        "rust",
        "go",
        "python",
        "java",
    }
    assert all(p["initial-version"] == "0.1.0" for p in config["packages"].values())
    assert config["packages"]["java"]["skip-snapshot"] is True
    extra = {lang: p.get("extra-files") for lang, p in config["packages"].items()}
    assert extra == {
        "typescript": ["src/core/version.ts"],
        "rust": None,
        "go": ["version.go"],
        "python": [f"src/grow_{svc.key_snake}/_version.py"],
        "java": ["pom.xml"],
    }
    assert json.loads((dest / ".release-please-manifest.json").read_text()) == dict.fromkeys(LANGS, "0.0.0")
    for name in ("docs/license.md", "README.md", "docs/index.md", "NOTICE", "SECURITY.md"):
        text = (dest / name).read_text(encoding="utf-8")
        assert "Inc.." not in text and "Inc.**." not in text, name

    scenarios = {p.name.split(".")[0] for p in (dest / "conformance" / "scenarios").glob("*.json")}
    assert scenarios == {"core", *svc.categories}
    assert (dest / "conformance" / "VERSION").read_text() == (
        REPO_ROOT / "conformance" / "VERSION"
    ).read_text()

    makefile = (dest / "Makefile").read_text(encoding="utf-8")
    assert f'project="{svc.key}-$$lang-' in makefile

    assert not sync(real_kit, dest).modified


def test_common_template_uses_only_known_tokens() -> None:
    known = set(DEMO.tokens())
    for path in COMMON.rglob("*"):
        if path.is_file() and not path.is_symlink():
            for name in re.findall(r"__([A-Z][A-Z_]*[A-Z])__", path.read_text(encoding="utf-8")):
                assert name in known, f"{path}: unknown token __{name}__"


def test_common_template_generated_headers() -> None:
    generated = {
        "AGENTS.md", "SECURITY.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "Makefile", ".gitignore",
        ".editorconfig",
    }  # fmt: skip
    owned = {"README.md", "NOTICE", "LICENSE", "release-please-config.json", ".release-please-manifest.json"}
    files = render(locate(), DEMO)
    for name in generated:
        assert files[name].generated, name
    for name in owned:
        assert not files[name].generated, name
    assert not files["skills/demo-sdk/SKILL.md"].generated


def test_real_template_renders_for_every_service() -> None:
    """The complete real template (all agents' parts) renders without errors or leftover tokens."""
    kit = locate()
    if not any((kit.template / lang).is_dir() for lang in LANGS):
        pytest.skip("language templates not written yet")
    for svc in ALL:
        files = render(kit, svc)
        for path, item in files.items():
            assert not LEFTOVER_RE.search(path), path
            if item.link is None and not path.startswith(("conformance/", "demo/")):
                text = item.data.decode("utf-8", errors="ignore")
                match = LEFTOVER_RE.search(text)
                assert match is None, f"{svc.key}: {path}: {match.group(0) if match else ''}"
        cats = set(svc.categories)
        for missing in set(CATEGORIES) - cats:
            assert not any(f"/{missing}/" in p for p in files), (svc.key, missing)


RELEASE_CHECK = ".github/scripts/release-check.py"


def run_release_check(dest: Path, what: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(dest / RELEASE_CHECK), what], capture_output=True, text=True, check=False
    )


def test_release_config_check_on_generated_repo(tmp_path: Path) -> None:
    """The generated release-check script accepts a fresh repo and names every broken rule."""
    kit = locate()
    if not all((kit.template / lang / "Makefile").is_file() for lang in LANGS):
        pytest.skip("language templates not written yet")
    svc = CATALOG[0]
    dest = tmp_path / svc.key
    new(kit, svc, dest)
    for what in ("config", "go", "typescript"):
        result = run_release_check(dest, what)
        assert result.returncode == 0, result.stderr
    usage = run_release_check(dest, "nope")
    assert usage.returncode == 2

    (dest / ".release-please-manifest.json").write_text('{"typescript": "0.2.0"}\n', encoding="utf-8")
    config = json.loads((dest / "release-please-config.json").read_text(encoding="utf-8"))
    config["packages"]["python"]["extra-files"] = []
    config["packages"]["rust"]["package-name"] = "grow-other"
    (dest / "release-please-config.json").write_text(json.dumps(config), encoding="utf-8")
    gomod = dest / "go" / "go.mod"
    gomod.write_text(gomod.read_text(encoding="utf-8") + "replace example.com/x => ../x\n", encoding="utf-8")
    result = run_release_check(dest, "config")
    assert result.returncode == 1
    for needle in (
        "'rust' missing or not a version",
        "packages.rust.package-name is 'grow-other'",
        "packages.python.extra-files must list",
        "typescript: package version is '0.1.0', release-please expects '0.2.0'",
        "replace directives",
    ):
        assert needle in result.stderr, needle
    assert run_release_check(dest, "go").returncode == 1


FAKE_NPM = """#!/bin/sh
case "$1" in
  pack) mkdir -p dist && : > dist/pkg-0.1.0.tgz ;;
  publish)
    case "$FAKE_PUBLISH" in
      ok) echo "+ pkg@0.1.0" ;;
      published)
        echo "npm notice Publishing to https://registry.npmjs.org/ with tag latest"
        echo "npm error You cannot publish over the previously published versions: 0.1.0." >&2
        exit 1 ;;
      *) echo "npm error 403 Forbidden" >&2; exit 1 ;;
    esac ;;
esac
"""


def test_typescript_release_check_tolerates_an_already_published_version(tmp_path: Path) -> None:
    """`make release-check` (TypeScript) passes when the dry run fails only because the version is on npm."""
    kit = locate()
    if not (kit.template / "typescript" / "Makefile").is_file():
        pytest.skip("typescript template not written yet")
    makefile = render(kit, DEMO)["typescript/Makefile"].data.decode("utf-8")
    assert 'grep -q "cannot publish over the previously published version"' in makefile
    assert "already on npm (expected between releases)" in makefile

    dest = tmp_path / "demo"
    new(kit, DEMO, dest)
    npm = tmp_path / "npm"
    npm.write_text(FAKE_NPM, encoding="utf-8")
    npm.chmod(0o755)

    def release_check(mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["make", "-s", "release-check", f"NPM={npm}", "RELEASE_CHECK=true"],
            cwd=dest / "typescript",
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin", "FAKE_PUBLISH": mode},
        )

    ok = release_check("ok")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "+ pkg@0.1.0" in ok.stdout
    published = release_check("published")
    assert published.returncode == 0, published.stdout + published.stderr
    assert "already on npm (expected between releases)" in published.stdout
    assert "npm notice Publishing" in published.stdout
    assert "npm error" not in published.stdout
    failed = release_check("forbidden")
    assert failed.returncode != 0
    assert "npm error 403 Forbidden" in failed.stdout
