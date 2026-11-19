"""``sdk-kit new`` and ``sdk-kit sync``: write a rendered repository to disk."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sdk_kit import __version__
from sdk_kit.kit import Kit
from sdk_kit.render import RenderedFile, is_generated_bytes, render
from sdk_kit.services import (
    DEFAULT_PACKAGE_VERSION,
    DEMO,
    LANGS,
    Service,
    ServiceError,
    find_service,
    normalize_categories,
)

MANIFEST = ".sdk-kit.json"
RELEASE_MANIFEST = ".release-please-manifest.json"
UNRELEASED = "0.0.0"
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


class GenerateError(RuntimeError):
    """The destination cannot be written (not empty, not an sdk-kit repo, ...)."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record(item: RenderedFile) -> dict[str, Any]:
    if item.link is not None:
        return {"path": item.path, "symlink": item.link}
    return {"path": item.path, "sha256": sha256(item.data), "generated": item.generated}


def _write(dest: Path, item: RenderedFile) -> None:
    target = dest / item.path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    if item.link is not None:
        target.symlink_to(item.link)
        return
    target.write_bytes(item.data)
    target.chmod(item.mode)


def _is_empty_dir(path: Path) -> bool:
    return not any(child.name != ".git" for child in path.iterdir())


@dataclass
class Manifest:
    """Content of ``.sdk-kit.json`` in a generated repository."""

    key: str
    categories: list[str]
    sdk_kit_version: str = __version__
    package_version: str = DEFAULT_PACKAGE_VERSION
    service: dict[str, Any] = field(default_factory=dict)
    files: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_json(self) -> str:
        data = {
            "sdkKitVersion": self.sdk_kit_version,
            "key": self.key,
            "categories": self.categories,
            "packageVersion": self.package_version,
            "service": self.service,
            "generatedFiles": [self.files[path] for path in sorted(self.files)],
        }
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def load(cls, dest: Path) -> Manifest:
        path = dest / MANIFEST
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise GenerateError(f"{dest} has no {MANIFEST}; generate it with 'sdk-kit new' first") from exc
        except json.JSONDecodeError as exc:
            raise GenerateError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("key"), str):
            raise GenerateError(f"{path} is not an sdk-kit manifest")
        entries = data.get("generatedFiles", [])
        files = {e["path"]: e for e in entries if isinstance(e, dict) and isinstance(e.get("path"), str)}
        return cls(
            key=data["key"],
            categories=list(data.get("categories", [])),
            sdk_kit_version=str(data.get("sdkKitVersion", "")),
            package_version=str(data.get("packageVersion", DEFAULT_PACKAGE_VERSION)),
            service=dict(data.get("service", {})),
            files=files,
        )

    def save(self, dest: Path) -> None:
        (dest / MANIFEST).write_text(self.to_json(), encoding="utf-8")


def new(
    kit: Kit,
    service: Service,
    dest: Path,
    *,
    force: bool = False,
    package_version: str = DEFAULT_PACKAGE_VERSION,
) -> list[str]:
    """Generate a new repository for ``service`` at ``dest``. Returns the written paths."""
    if dest.exists() and not dest.is_dir():
        raise GenerateError(f"{dest} exists and is not a directory")
    if dest.is_dir() and not _is_empty_dir(dest) and not force:
        raise GenerateError(f"{dest} is not empty; pass --force to overwrite")
    files = render(kit, service, package_version)
    dest.mkdir(parents=True, exist_ok=True)
    for item in files.values():
        _write(dest, item)
    Manifest(
        key=service.key,
        categories=list(service.categories),
        package_version=package_version,
        service=service.to_dict(),
        files={path: _record(item) for path, item in files.items()},
    ).save(dest)
    return list(files)


@dataclass
class SyncReport:
    """What ``sdk-kit sync`` did (or would do with ``dry_run``)."""

    updated: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)  # locally modified generated files, kept
    owned: list[str] = field(default_factory=list)  # header removed locally: now service-owned, kept

    @property
    def conflicts(self) -> bool:
        return bool(self.modified)


def _current(dest: Path, path: str) -> tuple[bytes | None, str | None]:
    """(file bytes, symlink target) of ``dest/path``; both ``None`` when it does not exist."""
    target = dest / path
    if target.is_symlink():
        return None, str(target.readlink())
    if target.is_file():
        return target.read_bytes(), None
    return None, None


def _sync_service(kit: Kit, manifest: Manifest, override: Service | None) -> Service:
    if override is not None:
        return override
    if manifest.key == DEMO.key:
        return DEMO
    try:
        return find_service(manifest.key, kit.services)
    except ServiceError:
        if not manifest.service:
            raise
        return Service.from_dict(manifest.service)


def released_versions(dest: Path) -> dict[str, str]:
    """Package versions release-please has released, per language (``.release-please-manifest.json``).

    Release PRs bump the version in generated files too (``typescript/src/core/version.ts``,
    ``java/pom.xml``), so ``sync`` renders those languages with the released version instead of
    the original ``packageVersion``. ``0.0.0`` means "not released yet" and is ignored.
    """
    try:
        data = json.loads((dest / RELEASE_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        lang: version
        for lang in LANGS
        if isinstance(version := data.get(lang), str) and _SEMVER_RE.match(version) and version != UNRELEASED
    }


def sync(
    kit: Kit,
    dest: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    service: Service | None = None,
    categories: tuple[str, ...] | None = None,
) -> SyncReport:
    """Re-render the template and refresh sdk-kit-owned files of an existing repository."""
    manifest = Manifest.load(dest)
    svc = _sync_service(kit, manifest, service)
    if svc.key != manifest.key:
        raise GenerateError(f"{dest} was generated for {manifest.key!r}, not {svc.key!r}")
    chosen = categories or (tuple(manifest.categories) if manifest.categories else svc.categories)
    svc = svc.with_categories(normalize_categories(list(chosen)))
    files = render(kit, svc, manifest.package_version, released_versions(dest))
    report = SyncReport()
    records = dict(manifest.files)

    def write(item: RenderedFile, bucket: list[str]) -> None:
        bucket.append(item.path)
        records[item.path] = _record(item)
        if not dry_run:
            _write(dest, item)

    for path, item in files.items():
        data, link = _current(dest, path)
        exists = data is not None or link is not None
        recorded = manifest.files.get(path)
        managed = item.generated or item.is_link or path.startswith("conformance/")
        if not exists:
            if managed or recorded is None:
                write(item, report.created)
            continue
        if (item.is_link and link == item.link) or (not item.is_link and data == item.data):
            report.unchanged.append(path)
            records[path] = _record(item)
            continue
        if not managed:
            continue  # service-owned file: never touched
        if item.generated and (data is None or not is_generated_bytes(data)):
            report.owned.append(path)
            continue
        pristine = recorded is not None and (
            (link is not None and recorded.get("symlink") == link)
            or (data is not None and recorded.get("sha256") == sha256(data))
        )
        if not pristine and not force:
            report.modified.append(path)
            continue
        write(item, report.updated)

    for path, recorded in manifest.files.items():
        if path in files:
            continue
        stale_managed = recorded.get("generated") or "symlink" in recorded or path.startswith("conformance/")
        if not stale_managed:
            continue
        data, link = _current(dest, path)
        if data is None and link is None:
            records.pop(path, None)
            continue
        pristine = (link is not None and recorded.get("symlink") == link) or (
            data is not None and recorded.get("sha256") == sha256(data)
        )
        if not pristine and not force:
            report.modified.append(path)
            continue
        report.removed.append(path)
        records.pop(path, None)
        if not dry_run:
            (dest / path).unlink()

    if not dry_run:
        manifest.sdk_kit_version = __version__
        manifest.categories = list(svc.categories)
        manifest.service = svc.to_dict()
        manifest.files = records
        manifest.save(dest)
    return report
