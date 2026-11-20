"""``sdk-kit versions`` (versions.json)."""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from sdk_kit import versions
from sdk_kit.cli import main
from sdk_kit.kit import Kit
from sdk_kit.services import load_catalog


def _manifest(root: Path, key: str, data: Any) -> None:
    (root / key).mkdir(parents=True, exist_ok=True)
    (root / key / ".release-please-manifest.json").write_text(json.dumps(data))


def test_manifest_from_dir(tmp_path: Path) -> None:
    _manifest(tmp_path, "a", {"typescript": "0.1.2", "go": 3})
    assert versions.manifest_from_dir(tmp_path, "a") == {"typescript": "0.1.2"}
    assert versions.manifest_from_dir(tmp_path, "missing") == {}
    _manifest(tmp_path, "list", [1])
    assert versions.manifest_from_dir(tmp_path, "list") == {}


def test_manifest_from_github_and_pypi() -> None:
    calls: list[str] = []

    def fetch(url: str) -> bytes | None:
        calls.append(url)
        if "missing" in url:
            return None
        if "pypi" in url:
            return b"{}"
        return b'{"python": "0.2.0", "x": 1}'

    assert versions.manifest_from_github("svc", fetch) == {"python": "0.2.0"}
    assert versions.manifest_from_github("missing", fetch) == {}
    assert "grow-codes-packages/svc/main" in calls[0]
    assert versions.pypi_available("grow-svc", "0.2.0", fetch)
    assert not versions.pypi_available("missing", "0.2.0", fetch)
    assert versions.manifest_from_github("arr", lambda _u: b"[]") == {}


def test_http_get(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resp(io.BytesIO):
        def __enter__(self) -> Resp:
            return self

        def __exit__(self, *_a: object) -> None:
            return None

    def ok(_req: object, timeout: float) -> Resp:
        return Resp(b"data")

    monkeypatch.setattr(versions.urllib.request, "urlopen", ok)
    assert versions.http_get("https://example.invalid/") == b"data"

    def not_found(req: Any, timeout: float) -> Resp:
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(versions.urllib.request, "urlopen", not_found)
    assert versions.http_get("https://example.invalid/") is None

    def boom(req: Any, timeout: float) -> Resp:
        raise urllib.error.HTTPError(req.full_url, 500, "err", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(versions.urllib.request, "urlopen", boom)
    with pytest.raises(urllib.error.HTTPError):
        versions.http_get("https://example.invalid/")


def test_build_versions(kit: Kit) -> None:
    services = load_catalog(kit.services)
    manifests = {
        services[0].key: {
            "typescript": "0.1.2",
            "go": "0.1.1",
            "python": "0.1.2",
            "java": "0.0.0",
            "rust": "0.1.0",
        }
    }
    doc = versions.build_versions(
        services,
        lambda key: manifests.get(key, {}),
        pypi=lambda name, v: v == "0.1.2",
        now=datetime(2026, 11, 20, tzinfo=timezone.utc),
    )
    assert doc["generatedAt"] == "2026-11-20T00:00:00Z" and doc["schema"] == 1
    first = doc["packages"][services[0].key]
    assert first["typescript"]["install"].endswith("@0.1.2") and first["typescript"]["available"]
    assert first["go"]["version"] == "v0.1.1" and first["go"]["install"].endswith("/go@v0.1.1")
    assert first["python"]["availableOnPypi"] is True
    assert first["python"]["install"].startswith("pip install grow-")
    assert first["java"]["version"] is None and first["java"]["available"] is False
    assert first["rust"]["install"].startswith("cargo add grow-")
    other = doc["packages"][services[1].key]
    assert other["python"]["install"] is None and other["python"]["available"] is False
    unknown = versions.package_versions(services[0], {"python": "0.3.0"})
    assert unknown["python"]["availableOnPypi"] is None
    assert unknown["python"]["install"] == f'pip install "{unknown["python"]["gitInstall"]}"'


def test_cli_versions(kit: Kit, tmp_path: Path) -> None:
    services = load_catalog(kit.services)
    root = tmp_path / "repos"
    _manifest(root, services[0].key, {"typescript": "1.0.0"})
    out = io.StringIO()
    assert main(["--kit-root", str(kit.root), "versions", "--repos-root", str(root)], out=out) == 0
    doc = json.loads(out.getvalue())
    assert doc["packages"][services[0].key]["typescript"]["version"] == "1.0.0"
    target = tmp_path / "versions.json"
    out = io.StringIO()
    code = main(
        ["--kit-root", str(kit.root), "versions", "--repos-root", str(root), "--out", str(target)],
        out=out,
    )
    assert code == 0 and "wrote" in out.getvalue() and json.loads(target.read_text())["schema"] == 1


def test_cli_versions_github(kit: Kit, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(versions, "http_get", lambda url, timeout=15.0: b'{"go": "0.1.0"}')
    monkeypatch.setattr("sdk_kit.cli.manifest_from_github", lambda key: {"go": "0.1.0"})
    monkeypatch.setattr("sdk_kit.cli.pypi_available", lambda name, v: False)
    out = io.StringIO()
    assert main(["--kit-root", str(kit.root), "versions", "--check-pypi"], out=out) == 0
    assert '"v0.1.0"' in out.getvalue()
