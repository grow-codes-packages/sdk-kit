"""Generate demo and every service of spec/services.json with the real repo-level template."""

from __future__ import annotations

import json
import re
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
    assert f"not affiliated with, endorsed or sponsored by {svc.vendor}" in notice.replace("\n", " ")
    assert f"{svc.display} is a trademark of {svc.vendor}" in notice.replace("\n", " ")
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
        "maven",
    }
    assert all(p["initial-version"] == "0.1.0" for p in config["packages"].values())
    assert json.loads((dest / ".release-please-manifest.json").read_text()) == {}

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
