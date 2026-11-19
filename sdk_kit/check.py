"""``sdk-kit check``: verify a generated repository still has everything sdk-kit requires."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from sdk_kit.generate import MANIFEST
from sdk_kit.render import GENERATED_MARKER, IGNORED_NAMES, decode_text, token_pattern
from sdk_kit.services import LANGS

GROW_CODES_BADGE = (
    "[![Grow Codes](https://img.shields.io/badge/Grow%20Codes-grow.codes-2ea44f)](https://grow.codes)"
)
WORKFLOWS = ("ci", "release", "docs")
# A workflow "calls sdk-kit" when it runs the CLI or uses a reusable workflow/action from the sdk-kit repo.
SDK_KIT_CALL_RE = re.compile(r"grow-codes-packages/sdk-kit|sdk-kit\s+(?:check|sync)\b")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
# Tokens from SPEC section 0 that must never survive generation.
LEFTOVER_RE = token_pattern(
    [
        "KEY", "KEY_SNAKE", "KEY_UPPER", "PKG", "SERVICE", "SERVICE_LOWER", "DISPLAY", "VENDOR",
        "UPSTREAM_LICENSE", "IMAGE", "PORT", "VERSION", "SDK_KIT_VERSION", "CATEGORIES",
    ]
)  # fmt: skip
SKIP_SCAN = IGNORED_NAMES | {".git"}
# Copied verbatim from sdk-kit (no token replacement), so not scanned for leftover tokens.
RAW_DIRS = frozenset({"conformance", "demo"})


def _readme_problems(readme: Path) -> list[str]:
    text = readme.read_text(encoding="utf-8", errors="replace")
    problems = []
    if GROW_CODES_BADGE not in text:
        problems.append("README.md: Grow Codes badge missing")
    required = {
        "CI badge": "actions/workflows/ci.yml/badge.svg",
        "licence badge": "img.shields.io/badge/license-Apache--2.0",
        "docs link": "https://grow-codes-packages.github.io/",
    }
    required.update({f"coverage badge ({lang})": f"badges/coverage-{lang}.json" for lang in LANGS})
    problems += [f"README.md: {name} missing" for name, needle in required.items() if needle not in text]
    return problems


def _leftover_tokens(dest: Path) -> list[str]:
    problems = []
    for dirpath, dirnames, filenames in os.walk(dest):
        top = Path(dirpath) == dest
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_SCAN and not (top and d in RAW_DIRS))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(dest).as_posix()
            if LEFTOVER_RE.search(rel):
                problems.append(f"{rel}: template token left in the path")
                continue
            text = decode_text(path.read_bytes())
            match = LEFTOVER_RE.search(text) if text is not None else None
            if match:
                line = text[: match.start()].count("\n") + 1 if text else 0
                problems.append(f"{rel}:{line}: template token {match.group(0)} left unreplaced")
    return problems


def check(dest: Path, key: str | None = None) -> list[str]:
    """Return the list of problems (empty when the repository is fine)."""
    if not dest.is_dir():
        return [f"{dest} is not a directory"]
    problems: list[str] = []
    manifest_path = dest / MANIFEST
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            key = key or str(data["key"])
        except (json.JSONDecodeError, KeyError, TypeError):
            problems.append(f"{MANIFEST}: not a valid sdk-kit manifest")
    else:
        problems.append(f"{MANIFEST} missing")
    key = key or dest.resolve().name

    required = [
        "LICENSE", "NOTICE", "README.md", "AGENTS.md", "SECURITY.md", "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md", "Makefile", f"skills/{key}-sdk/SKILL.md", "docker/compose.yml",
        "conformance/VERSION", "release-please-config.json", ".release-please-manifest.json",
    ]  # fmt: skip
    required += [f"{lang}/Makefile" for lang in LANGS]
    required += [f"docker/Dockerfile.{lang}" for lang in LANGS]
    required += [f".github/workflows/{name}.yml" for name in WORKFLOWS]
    problems += [f"{rel} missing" for rel in required if not (dest / rel).is_file()]

    license_file = dest / "LICENSE"
    if license_file.is_file():
        text = license_file.read_text(encoding="utf-8", errors="replace")
        if "Apache License" not in text or "Version 2.0" not in text:
            problems.append("LICENSE: not the Apache-2.0 licence text")
    notice = dest / "NOTICE"
    if notice.is_file() and "Grow Codes" not in notice.read_text(encoding="utf-8", errors="replace"):
        problems.append("NOTICE: Grow Codes copyright missing")
    readme = dest / "README.md"
    if readme.is_file():
        problems += _readme_problems(readme)
    claude = dest / "CLAUDE.md"
    if not claude.is_symlink() or str(claude.readlink()) != "AGENTS.md":
        problems.append("CLAUDE.md must be a symlink to AGENTS.md")
    version = dest / "conformance" / "VERSION"
    if version.is_file() and not VERSION_RE.match(version.read_text(encoding="utf-8").strip()):
        problems.append("conformance/VERSION: not a version number")

    workflow_dir = dest / ".github" / "workflows"
    texts = [
        "\n".join(
            line
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines()
            if GENERATED_MARKER not in line
        )  # the header itself mentions "sdk-kit sync"
        for p in sorted(workflow_dir.glob("*.y*ml"))
    ]
    if not any(SDK_KIT_CALL_RE.search(text) for text in texts):
        problems.append(
            ".github/workflows: no workflow calls sdk-kit (sdk-kit check/sync or a reusable workflow)"
        )

    problems += _leftover_tokens(dest)
    return problems
