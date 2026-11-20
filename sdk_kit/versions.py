"""``sdk-kit versions``: the released version of every package per language (``versions.json``).

Source of truth for consumers (the platform workflows, templates, agents) instead of hand-written
version maps. Each service repository's ``.release-please-manifest.json`` holds the last released
version per language; the result names the exact install command for each one. PyPI may lack a
package (new-project limit): with ``check`` the PyPI JSON API is asked and ``available: false``
switches the Python install command to the git tag.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sdk_kit import __version__
from sdk_kit.services import LANGS, Service

GITHUB_ORG = "grow-codes-packages"
RAW_URL = "https://raw.githubusercontent.com/{org}/{key}/main/.release-please-manifest.json"
PYPI_URL = "https://pypi.org/pypi/{name}/{version}/json"
UNRELEASED = "0.0.0"

Fetch = Callable[[str], "bytes | None"]


def http_get(url: str, timeout: float = 15.0) -> bytes | None:
    """GET ``url``; ``None`` for 404 (anything else raises ``OSError``)."""
    request = urllib.request.Request(url, headers={"User-Agent": f"sdk-kit/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data: bytes = response.read()
            return data
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def manifest_from_dir(root: Path, key: str) -> dict[str, str]:
    """``.release-please-manifest.json`` of the local clone ``root/<key>`` (empty when missing)."""
    path = root / key / ".release-please-manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}


def manifest_from_github(key: str, fetch: Fetch = http_get) -> dict[str, str]:
    """``.release-please-manifest.json`` on ``main`` of the GitHub repository (empty when missing)."""
    raw = fetch(RAW_URL.format(org=GITHUB_ORG, key=key))
    if raw is None:
        return {}
    data = json.loads(raw.decode("utf-8"))
    return {k: v for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}


def pypi_available(name: str, version: str, fetch: Fetch = http_get) -> bool:
    """Whether PyPI serves ``name==version``."""
    return fetch(PYPI_URL.format(name=name, version=version)) is not None


def _names(svc: Service) -> dict[str, str]:
    extra = svc.extra
    return {
        "npm": str(extra.get("npm") or f"@grow-codes/{svc.key}"),
        "crate": str(extra.get("crate") or f"grow-{svc.key}"),
        "pypi": str(extra.get("pypi") or f"grow-{svc.key}"),
        "pyImport": str(extra.get("pyImport") or f"grow_{svc.key_snake}"),
        "goModule": str(extra.get("goModule") or f"github.com/{GITHUB_ORG}/{svc.key}/go"),
        "maven": str(extra.get("maven") or f"codes.grow.packages:{svc.key}"),
    }


def package_versions(
    svc: Service, manifest: dict[str, str], *, pypi: Callable[[str, str], bool] | None = None
) -> dict[str, Any]:
    """The ``versions.json`` entry of one service: per language name, version, install command.

    A language without a release (missing or ``0.0.0``) gets ``version: null`` and
    ``available: false``. ``pypi`` checks PyPI; without it Python ``available`` is ``null``
    (unknown) and the install command is the git tag form, which always works.
    """
    n = _names(svc)
    git = f"git+https://github.com/{GITHUB_ORG}/{svc.key}"
    out: dict[str, Any] = {"display": svc.display, "categories": list(svc.categories)}
    for lang in LANGS:
        version = manifest.get(lang)
        released = bool(version) and version != UNRELEASED
        v = version if released else None
        entry: dict[str, Any]
        if lang == "typescript":
            entry = {"package": n["npm"], "install": f"npm i {n['npm']}@{v}" if v else None}
        elif lang == "rust":
            entry = {"package": n["crate"], "install": f"cargo add {n['crate']}@{v}" if v else None}
        elif lang == "go":
            entry = {"module": n["goModule"], "install": f"go get {n['goModule']}@v{v}" if v else None}
            v = f"v{v}" if v else None
        elif lang == "java":
            entry = {"package": n["maven"], "install": f"{n['maven']}:{v}" if v else None}
        else:
            available = None if (pypi is None or not v) else pypi(n["pypi"], v)
            tag = f"{n['pypi']} @ {git}@python-v{v}#subdirectory=python" if v else None
            entry = {
                "package": n["pypi"],
                "import": n["pyImport"],
                "availableOnPypi": available,
                "install": (f"pip install {n['pypi']}=={v}" if available else f'pip install "{tag}"')
                if v
                else None,
                "gitInstall": tag,
            }
        entry["version"] = v
        entry.setdefault("available", released if lang != "python" else bool(v))
        out[lang] = entry
    return out


def build_versions(
    services: list[Service],
    manifest: Callable[[str], dict[str, str]],
    *,
    pypi: Callable[[str, str], bool] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The whole ``versions.json`` document for ``services``."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema": 1,
        "generatedAt": stamp,
        "sdkKit": __version__,
        "packages": {s.key: package_versions(s, manifest(s.key), pypi=pypi) for s in services},
    }
