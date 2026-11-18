from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from sdk_kit.check import check
from sdk_kit.generate import MANIFEST, new
from sdk_kit.kit import Kit
from sdk_kit.services import Service
from tests.conftest import STUB_SERVICES, write

ALPHA = Service.from_dict(STUB_SERVICES[0])


@pytest.fixture
def repo(kit: Kit, tmp_path: Path) -> Path:
    dest = tmp_path / "alpha-secrets"
    new(kit, ALPHA, dest)
    return dest


def test_check_passes_on_generated_repo(repo: Path) -> None:
    assert check(repo) == []


def test_check_not_a_directory(tmp_path: Path) -> None:
    assert check(tmp_path / "missing") == [f"{tmp_path / 'missing'} is not a directory"]


def _rm(rel: str) -> Callable[[Path], None]:
    return lambda repo: (repo / rel).unlink()


def _edit(rel: str, old: str, new_text: str) -> Callable[[Path], None]:
    def apply(repo: Path) -> None:
        path = repo / rel
        path.write_text(path.read_text().replace(old, new_text))

    return apply


def _put(rel: str, content: str) -> Callable[[Path], None]:
    return lambda repo: write(repo / rel, content) and None


@pytest.mark.parametrize(
    ("mutate", "problem"),
    [
        (_rm("LICENSE"), "LICENSE missing"),
        (_rm("NOTICE"), "NOTICE missing"),
        (_rm("skills/alpha-secrets-sdk/SKILL.md"), "skills/alpha-secrets-sdk/SKILL.md missing"),
        (_rm("go/Makefile"), "go/Makefile missing"),
        (_rm("docker/compose.yml"), "docker/compose.yml missing"),
        (_rm("docker/Dockerfile.java"), "docker/Dockerfile.java missing"),
        (_rm("conformance/VERSION"), "conformance/VERSION missing"),
        (_rm(".github/workflows/release.yml"), ".github/workflows/release.yml missing"),
        (_put("LICENSE", "MIT License\n"), "LICENSE: not the Apache-2.0 licence text"),
        (_put("NOTICE", "nothing\n"), "NOTICE: Grow Codes copyright missing"),
        (_edit("README.md", "[![Grow Codes]", "[![Grow]"), "README.md: Grow Codes badge missing"),
        (
            _edit("README.md", "coverage-rust.json", "cov-rust.json"),
            "README.md: coverage badge (rust) missing",
        ),
        (_edit("README.md", "actions/workflows/ci.yml/badge.svg", "x.svg"), "README.md: CI badge missing"),
        (_put("conformance/VERSION", "latest\n"), "conformance/VERSION: not a version number"),
        (_rm("CLAUDE.md"), "CLAUDE.md must be a symlink to AGENTS.md"),
        (_put(".github/workflows/ci.yml", "name: ci\n"), "no workflow calls sdk-kit"),
        (_put("go/extra.go", "package __PKG__\n"), "go/extra.go:1: template token __PKG__ left unreplaced"),
        (_put("go/__KEY__.txt", "x"), "go/__KEY__.txt: template token left in the path"),
        (_rm(MANIFEST), ".sdk-kit.json missing"),
        (_put(MANIFEST, "[]"), ".sdk-kit.json: not a valid sdk-kit manifest"),
    ],
)
def test_check_reports_problems(repo: Path, mutate: Callable[[Path], None], problem: str) -> None:
    mutate(repo)
    problems = check(repo)
    assert any(problem in p for p in problems), problems


def test_check_claude_regular_file(repo: Path) -> None:
    (repo / "CLAUDE.md").unlink()
    (repo / "CLAUDE.md").write_text("copy")
    assert "CLAUDE.md must be a symlink to AGENTS.md" in check(repo)


def test_check_reusable_workflow_counts(repo: Path) -> None:
    write(
        repo / ".github" / "workflows" / "ci.yml",
        "jobs:\n  ci:\n    uses: grow-codes-packages/sdk-kit/.github/workflows/sdk-ci.yml@v0\n",
    )
    assert check(repo) == []


def test_check_key_from_dir_name_and_option(repo: Path) -> None:
    (repo / MANIFEST).unlink()
    assert check(repo) == [".sdk-kit.json missing"]  # dir name is the key
    renamed = repo.parent / "renamed"
    repo.rename(renamed)
    assert "skills/renamed-sdk/SKILL.md missing" in check(renamed)
    assert check(renamed, key="alpha-secrets") == [".sdk-kit.json missing"]


def test_check_skips_ignored_dirs_and_binaries(repo: Path) -> None:
    write(repo / "typescript" / "node_modules" / "pkg" / "x.js", "__KEY__")
    write(repo / ".git" / "HEAD", "__KEY__")
    write(repo / "img.bin", b"\0__KEY__")
    (repo / "go" / "link").symlink_to("missing-target")
    assert check(repo) == []


def test_check_manifest_key_missing(repo: Path) -> None:
    (repo / MANIFEST).write_text(json.dumps({"nokey": 1}))
    assert check(repo) == [".sdk-kit.json: not a valid sdk-kit manifest"]
