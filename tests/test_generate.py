from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from sdk_kit import __version__
from sdk_kit.generate import MANIFEST, GenerateError, Manifest, new, released_versions, sync
from sdk_kit.kit import Kit
from sdk_kit.services import DEMO, Service, ServiceError
from tests.conftest import STUB_SERVICES, write

ALPHA = Service.from_dict(STUB_SERVICES[0])
BETA = Service.from_dict(STUB_SERVICES[1])


def manifest(dest: Path) -> dict[str, object]:
    return json.loads((dest / MANIFEST).read_text(encoding="utf-8"))


def entries(dest: Path) -> dict[str, dict[str, object]]:
    data = manifest(dest)
    return {e["path"]: e for e in data["generatedFiles"]}  # type: ignore[index,union-attr]


def test_new_writes_repo_and_manifest(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "out" / "alpha"
    written = new(kit, ALPHA, dest, package_version="0.3.0")
    assert "README.md" in written
    assert (dest / "CLAUDE.md").is_symlink()
    assert (dest / "CLAUDE.md").readlink() == Path("AGENTS.md")
    script = dest / "go" / "scripts" / "run.sh"
    assert stat.S_IMODE(script.stat().st_mode) == 0o755
    assert stat.S_IMODE((dest / "go" / "client.go").stat().st_mode) == 0o644
    assert (dest / "conformance" / "VERSION").read_text() == "0.1.0\n"
    assert "GROW_ALPHA_SECRETS_URL" in (dest / "go" / "client.go").read_text()
    data = manifest(dest)
    assert data["sdkKitVersion"] == __version__
    assert data["key"] == "alpha-secrets"
    assert data["categories"] == ["secrets"]
    assert data["packageVersion"] == "0.3.0"
    assert data["service"]["pkg"] == "alphasecrets"  # type: ignore[index]
    files = entries(dest)
    assert files["CLAUDE.md"] == {"path": "CLAUDE.md", "symlink": "AGENTS.md"}
    readme = files["README.md"]
    assert readme["sha256"] == hashlib.sha256((dest / "README.md").read_bytes()).hexdigest()
    assert readme["generated"] is False
    assert files["go/src/core/errors.go"]["generated"] is True
    assert MANIFEST not in files


def test_new_refuses_non_empty_dest(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "busy"
    write(dest / "keep.txt", "mine")
    with pytest.raises(GenerateError, match="not empty"):
        new(kit, ALPHA, dest)
    new(kit, ALPHA, dest, force=True)
    assert (dest / "keep.txt").read_text() == "mine"
    assert (dest / "README.md").is_file()


def test_new_force_replaces_conflicting_entries(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "conflict"
    (dest / "README.md").mkdir(parents=True)
    write(dest / "README.md" / "x", "dir in the way")
    write(dest / "AGENTS.md", "old")
    (dest / "CLAUDE.md").symlink_to("elsewhere.md")
    new(kit, ALPHA, dest, force=True)
    assert (dest / "README.md").is_file()
    assert (dest / "CLAUDE.md").readlink() == Path("AGENTS.md")


def test_new_allows_git_only_dir_and_rejects_file(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "gitonly"
    (dest / ".git").mkdir(parents=True)
    new(kit, ALPHA, dest)
    assert (dest / "README.md").is_file()
    file_dest = tmp_path / "file"
    file_dest.write_text("x")
    with pytest.raises(GenerateError, match="not a directory"):
        new(kit, ALPHA, file_dest, force=True)


def test_sync_noop_when_nothing_changed(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(kit, ALPHA, dest)
    report = sync(kit, dest)
    assert not report.updated and not report.created and not report.removed and not report.modified
    assert "README.md" in report.unchanged
    assert not report.conflicts


def test_sync_updates_generated_and_conformance_only(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(kit, ALPHA, dest)
    errors_tpl = kit.template / "go" / "src" / "core" / "errors.go"
    errors_tpl.write_text(errors_tpl.read_text() + "// new line\n")
    (kit.template / "go" / "client.go").write_text("// changed owned skeleton\n")
    (kit.template / "common" / "README.md").write_text("# changed README\n")
    write(kit.conformance / "scenarios" / "secrets.new.json", "{}")
    (kit.conformance / "VERSION").write_text("0.2.0\n")
    report = sync(kit, dest)
    assert sorted(report.updated) == ["conformance/VERSION", "go/src/core/errors.go"]
    assert report.created == ["conformance/scenarios/secrets.new.json"]
    assert (dest / "go" / "src" / "core" / "errors.go").read_text().endswith("// new line\n")
    assert (dest / "go" / "client.go").read_text().startswith("// service-owned client")
    assert (dest / "README.md").read_text() != "# changed README\n"
    files = entries(dest)
    assert (
        files["go/src/core/errors.go"]["sha256"]
        == hashlib.sha256((dest / "go" / "src" / "core" / "errors.go").read_bytes()).hexdigest()
    )


def test_sync_skips_locally_modified_unless_forced(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(kit, ALPHA, dest)
    target = dest / "rust" / "src" / "core" / "errors.rs"
    target.write_text(target.read_text() + "// local hack\n")
    (dest / "conformance" / "core-unit.md").write_text("local edit\n")
    tpl = kit.template / "rust" / "src" / "core" / "errors.rs"
    tpl.write_text(tpl.read_text() + "// upstream change\n")
    report = sync(kit, dest)
    assert sorted(report.modified) == ["conformance/core-unit.md", "rust/src/core/errors.rs"]
    assert report.conflicts
    assert "local hack" in target.read_text()
    forced = sync(kit, dest, force=True)
    assert sorted(forced.updated) == ["conformance/core-unit.md", "rust/src/core/errors.rs"]
    assert "upstream change" in target.read_text() and "local hack" not in target.read_text()


def test_sync_header_removed_means_service_owned(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(kit, ALPHA, dest)
    target = dest / "python" / "src" / "core" / "errors.py"
    target.write_text("# taken over by the service\n")
    report = sync(kit, dest, force=True)
    assert report.owned == ["python/src/core/errors.py"]
    assert target.read_text() == "# taken over by the service\n"


def test_sync_unrecorded_generated_file_counts_as_modified(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(kit, ALPHA, dest)
    write(kit.template / "go" / "src" / "core" / "extra.go", "// Generated by sdk-kit x\n// v2\n")
    write(dest / "go" / "src" / "core" / "extra.go", "// Generated by sdk-kit x\n// handmade\n")
    report = sync(kit, dest)
    assert report.modified == ["go/src/core/extra.go"]


def test_sync_symlink_restored_and_replaced(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(kit, ALPHA, dest)
    (dest / "CLAUDE.md").unlink()
    report = sync(kit, dest)
    assert report.created == ["CLAUDE.md"]
    (dest / "CLAUDE.md").unlink()
    (dest / "CLAUDE.md").symlink_to("README.md")
    assert sync(kit, dest).modified == ["CLAUDE.md"]
    assert sync(kit, dest, force=True).updated == ["CLAUDE.md"]
    assert (dest / "CLAUDE.md").readlink() == Path("AGENTS.md")


def test_sync_recorded_symlink_is_pristine(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    (kit.template / "go" / "current").symlink_to("src")
    new(kit, ALPHA, dest)
    (kit.template / "go" / "current").unlink()
    (kit.template / "go" / "current").symlink_to("zapadapter")
    report = sync(kit, dest)
    assert report.updated == ["go/current"]
    assert (dest / "go" / "current").readlink() == Path("zapadapter")


def test_sync_owned_files_created_once(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(kit, ALPHA, dest)
    write(kit.template / "go" / "options.go", "// new service-owned skeleton for __PKG__\n")
    report = sync(kit, dest)
    assert report.created == ["go/options.go"]
    assert (dest / "go" / "options.go").read_text() == "// new service-owned skeleton for alphasecrets\n"
    (dest / "go" / "client.go").unlink()  # the service deleted its skeleton on purpose
    report = sync(kit, dest)
    assert "go/client.go" not in report.created
    assert not (dest / "go" / "client.go").exists()


def test_sync_recreates_deleted_generated_file(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(kit, ALPHA, dest)
    (dest / "go" / "src" / "core" / "errors.go").unlink()
    report = sync(kit, dest)
    assert report.created == ["go/src/core/errors.go"]


def test_sync_category_change_removes_stale_generated(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "beta"
    new(kit, BETA, dest)
    assert (dest / "go" / "zapadapter" / "core.go").is_file()
    (dest / "go" / "src" / "tracing_setup.go").write_text("// Generated by sdk-kit\n// local\n")
    dry = sync(kit, dest, categories=("tracing",), dry_run=True)
    assert "go/zapadapter/core.go" in dry.removed
    assert (dest / "go" / "zapadapter" / "core.go").is_file()
    assert manifest(dest)["categories"] == ["logging", "tracing"]
    report = sync(kit, dest, categories=("tracing",))
    assert "go/zapadapter/core.go" in report.removed
    assert "conformance/scenarios/logging.batch.json" in report.removed
    assert "go/src/tracing_setup.go" in report.modified
    assert not (dest / "go" / "zapadapter" / "core.go").exists()
    assert manifest(dest)["categories"] == ["tracing"]
    assert "go/zapadapter/core.go" not in entries(dest)


def test_sync_stale_modified_kept_unless_forced(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "beta"
    new(kit, BETA, dest)
    adapter = dest / "go" / "zapadapter" / "core.go"
    adapter.write_text("// Generated by sdk-kit\n// local change\n")
    (dest / "rust" / "zapadapter" / "core.rs").unlink()
    report = sync(kit, dest, categories=("tracing",))
    assert "go/zapadapter/core.go" in report.modified
    assert "rust/zapadapter/core.rs" not in report.removed
    assert adapter.exists()
    forced = sync(kit, dest, categories=("tracing",), force=True)
    assert "go/zapadapter/core.go" in forced.removed
    assert not adapter.exists()


def test_sync_stale_symlink_and_owned(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    (kit.template / "go" / "current").symlink_to("src")
    new(kit, ALPHA, dest)
    (kit.template / "go" / "current").unlink()
    (kit.template / "go" / "client.go").unlink()
    report = sync(kit, dest)
    assert report.removed == ["go/current"]
    assert (dest / "go" / "client.go").is_file()  # owned files are never removed
    assert "go/client.go" in entries(dest)


def test_sync_dry_run_writes_nothing(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "alpha"
    new(kit, ALPHA, dest)
    before = (dest / MANIFEST).read_text()
    tpl = kit.template / "go" / "src" / "core" / "errors.go"
    tpl.write_text(tpl.read_text() + "// more\n")
    report = sync(kit, dest, dry_run=True)
    assert report.updated == ["go/src/core/errors.go"]
    assert "more" not in (dest / "go" / "src" / "core" / "errors.go").read_text()
    assert (dest / MANIFEST).read_text() == before


def test_sync_errors(kit: Kit, tmp_path: Path) -> None:
    with pytest.raises(GenerateError, match=r"no \.sdk-kit\.json"):
        sync(kit, tmp_path)
    (tmp_path / MANIFEST).write_text("{")
    with pytest.raises(GenerateError, match="not valid JSON"):
        sync(kit, tmp_path)
    (tmp_path / MANIFEST).write_text("[]")
    with pytest.raises(GenerateError, match="not an sdk-kit manifest"):
        sync(kit, tmp_path)
    dest = tmp_path / "alpha"
    new(kit, ALPHA, dest)
    with pytest.raises(GenerateError, match="generated for 'alpha-secrets', not 'beta-obs'"):
        sync(kit, dest, service=BETA)


def test_sync_custom_service_from_manifest(kit: Kit, tmp_path: Path) -> None:
    custom = Service.from_dict(
        {**STUB_SERVICES[0], "key": "custom-thing", "service": "Custom", "pkg": "custom"}
    )
    dest = tmp_path / "custom"
    new(kit, custom, dest)
    report = sync(kit, dest)
    assert not report.modified and not report.updated
    data = manifest(dest)
    data["service"] = {}
    (dest / MANIFEST).write_text(json.dumps(data))
    with pytest.raises(ServiceError, match="unknown service"):
        sync(kit, dest)


def test_sync_demo_and_explicit_service(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "demo"
    new(kit, DEMO, dest)
    assert (dest / "docker" / "demo" / "server.py").is_file()
    assert sync(kit, dest).unchanged
    dest2 = tmp_path / "alpha"
    new(kit, ALPHA, dest2)
    changed = Service.from_dict({**STUB_SERVICES[0], "image": "alpha/alpha:9.9.9"})
    report = sync(kit, dest2, service=changed)
    assert "docker/compose.yml" in report.updated
    assert "alpha/alpha:9.9.9" in (dest2 / "docker" / "compose.yml").read_text()


def test_manifest_round_trip(tmp_path: Path) -> None:
    m = Manifest(key="k", categories=["secrets"], files={"b": {"path": "b"}, "a": {"path": "a"}})
    m.save(tmp_path)
    loaded = Manifest.load(tmp_path)
    assert loaded.key == "k" and list(loaded.files) == ["a", "b"]
    (tmp_path / MANIFEST).write_text(json.dumps({"key": "k", "generatedFiles": [{"nopath": 1}, "x"]}))
    loaded = Manifest.load(tmp_path)
    assert loaded.files == {} and loaded.categories == [] and loaded.package_version == "0.1.0"


VERSION_TS = 'export const SDK_VERSION = "{v}"; // x-release-please-version\n'


def test_released_versions(tmp_path: Path) -> None:
    assert released_versions(tmp_path) == {}
    write(tmp_path / ".release-please-manifest.json", "not json")
    assert released_versions(tmp_path) == {}
    write(tmp_path / ".release-please-manifest.json", "[]")
    assert released_versions(tmp_path) == {}
    write(
        tmp_path / ".release-please-manifest.json",
        json.dumps(
            {
                "typescript": "0.2.0",
                "go": "0.0.0",
                "rust": "x",
                "java": 3,
                "other": "1.0.0",
                "python": "1.0.0-rc.1",
            }
        ),
    )
    assert released_versions(tmp_path) == {"typescript": "0.2.0", "python": "1.0.0-rc.1"}


def test_sync_renders_released_versions(kit: Kit, tmp_path: Path) -> None:
    """A release PR bumps versions inside generated files; sync must not undo or flag that."""
    header = (
        '// Generated by sdk-kit __SDK_KIT_VERSION__ — do not edit; change sdk-kit and run "sdk-kit sync"\n'
    )
    for lang in ("typescript", "go"):
        write(
            kit.template / lang / "src" / "core" / "version.ts", header + VERSION_TS.format(v="__VERSION__")
        )
    write(kit.template / "examples" / "typescript" / "version.txt", "__VERSION__\n")
    dest = tmp_path / "alpha"
    new(kit, ALPHA, dest)
    ts, go = dest / "typescript" / "src" / "core" / "version.ts", dest / "go" / "src" / "core" / "version.ts"
    assert VERSION_TS.format(v="0.1.0") in ts.read_text(encoding="utf-8")
    write(dest / ".release-please-manifest.json", json.dumps({"typescript": "0.2.0", "go": "0.0.0"}))
    ts.write_text(
        ts.read_text(encoding="utf-8").replace(VERSION_TS.format(v="0.1.0"), VERSION_TS.format(v="0.2.0")),
        encoding="utf-8",
    )
    report = sync(kit, dest)
    assert not report.modified and not report.updated
    assert "typescript/src/core/version.ts" in report.unchanged
    assert VERSION_TS.format(v="0.2.0") in ts.read_text(encoding="utf-8")
    assert VERSION_TS.format(v="0.1.0") in go.read_text(encoding="utf-8")
    assert (dest / "examples" / "typescript" / "version.txt").read_text(encoding="utf-8") == "0.1.0\n"
