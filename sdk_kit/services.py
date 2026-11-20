"""Service catalog loading and template token values (SPEC section 0)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sdk_kit import __version__

CATEGORIES: tuple[str, ...] = ("secrets", "logging", "tracing", "auth")
"""Every category in canonical order. ``auth`` (token verification, identity providers) has no
shared template code yet: an ``auth`` service gets the core and owns its auth code."""
SERVICE_CATEGORIES: tuple[str, ...] = ("secrets", "logging", "tracing")
"""The categories of the demo service (the ones with shared template code)."""
LANGS: tuple[str, ...] = ("typescript", "rust", "go", "python", "java")
DEFAULT_PACKAGE_VERSION = "0.1.0"

_KEY_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_PKG_RE = re.compile(r"^[a-z][a-z0-9]*$")
_SERVICE_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")

REQUIRED_FIELDS: tuple[str, ...] = ("key", "display", "service", "pkg", "categories")


class ServiceError(ValueError):
    """Raised for an unknown service or an invalid service definition."""


def normalize_categories(values: list[str] | tuple[str, ...] | str) -> tuple[str, ...]:
    """Validate categories and return them in canonical order (secrets, logging, tracing, auth)."""
    items: list[str] = []
    raw = [values] if isinstance(values, str) else list(values)
    for value in raw:
        items.extend(part.strip() for part in value.split(","))
    chosen = {item for item in items if item}
    unknown = sorted(chosen - set(CATEGORIES))
    if unknown:
        raise ServiceError(
            f"unknown categor{'ies' if len(unknown) > 1 else 'y'}: {', '.join(unknown)} "
            f"(allowed: {', '.join(CATEGORIES)})"
        )
    if not chosen:
        raise ServiceError("a service needs at least one category")
    return tuple(c for c in CATEGORIES if c in chosen)


def lower_camel(name: str) -> str:
    """camelCase of a PascalCase name: ``OpenBao`` -> ``openBao``."""
    return name[:1].lower() + name[1:]


@dataclass(frozen=True)
class Service:
    """One service of the catalog with everything needed for the template tokens."""

    key: str
    display: str
    service: str
    pkg: str
    categories: tuple[str, ...]
    image: str = ""
    port: str = ""
    vendor: str = ""
    upstream_license: str = ""
    env: str = ""
    key_snake: str = ""
    key_upper: str = ""
    extra: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Service:
        """Build and validate a service from a catalog entry (``spec/services.json`` format)."""
        if not isinstance(data, dict):
            raise ServiceError("a service definition must be a JSON object")
        missing = [name for name in REQUIRED_FIELDS if not data.get(name)]
        if missing:
            raise ServiceError(f"service definition misses: {', '.join(missing)}")
        key = str(data["key"])
        if not _KEY_RE.match(key):
            raise ServiceError(f"invalid key {key!r}: use lower-case words joined by '-'")
        pkg = str(data["pkg"])
        if not _PKG_RE.match(pkg):
            raise ServiceError(f"invalid pkg {pkg!r}: lower-case letters and digits only")
        service = str(data["service"])
        if not _SERVICE_RE.match(service):
            raise ServiceError(f"invalid service {service!r}: PascalCase letters and digits only")
        known = {
            "key", "display", "service", "pkg", "categories", "image", "port", "vendor",
            "upstreamLicense", "env", "keySnake", "keyUpper",
        }  # fmt: skip
        return cls(
            key=key,
            display=str(data["display"]),
            service=service,
            pkg=pkg,
            categories=normalize_categories(data["categories"]),
            image=str(data.get("image", "")),
            port=str(data.get("port", "")),
            vendor=str(data.get("vendor", "")),
            upstream_license=str(data.get("upstreamLicense", "")),
            env=str(data.get("env", "")),
            key_snake=str(data.get("keySnake") or key.replace("-", "_")),
            key_upper=str(data.get("keyUpper") or key.replace("-", "_").upper()),
            extra={k: v for k, v in data.items() if k not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        """Catalog-format dictionary (round-trips through :meth:`from_dict`)."""
        data: dict[str, Any] = {
            "key": self.key,
            "display": self.display,
            "service": self.service,
            "pkg": self.pkg,
            "keySnake": self.key_snake,
            "keyUpper": self.key_upper,
            "categories": list(self.categories),
            "image": self.image,
            "port": self.port,
            "upstreamLicense": self.upstream_license,
            "vendor": self.vendor,
            "env": self.env,
        }
        data.update(self.extra)
        return data

    def with_categories(self, categories: tuple[str, ...]) -> Service:
        """Copy of this service with other categories."""
        return Service(
            key=self.key,
            display=self.display,
            service=self.service,
            pkg=self.pkg,
            categories=categories,
            image=self.image,
            port=self.port,
            vendor=self.vendor,
            upstream_license=self.upstream_license,
            env=self.env,
            key_snake=self.key_snake,
            key_upper=self.key_upper,
            extra=dict(self.extra),
        )

    def tokens(self, package_version: str = DEFAULT_PACKAGE_VERSION) -> dict[str, str]:
        """Token name (without underscores) -> value, per SPEC section 0."""
        return {
            "KEY": self.key,
            "KEY_SNAKE": self.key_snake,
            "KEY_UPPER": self.key_upper,
            "PKG": self.pkg,
            "SERVICE": self.service,
            "SERVICE_LOWER": lower_camel(self.service),
            "DISPLAY": self.display,
            "VENDOR": self.vendor,
            "UPSTREAM_LICENSE": self.upstream_license,
            "IMAGE": self.image,
            "PORT": self.port,
            "VERSION": package_version,
            "SDK_KIT_VERSION": __version__,
            "CATEGORIES": ",".join(self.categories),
            # Not in SPEC section 0: vendor environment variables, used by README/docs only.
            "ENV": self.env,
        }


DEMO = Service(
    key="demo",
    display="Demo",
    service="Demo",
    pkg="demo",
    categories=SERVICE_CATEGORIES,
    image="sdk-kit-demo",
    port="8080",
    vendor="Grow Codes",
    upstream_license="Apache-2.0 (sdk-kit demo server)",
    env="`GROW_DEMO_*`",
    key_snake="demo",
    key_upper="DEMO",
)


def load_catalog(path: Path) -> list[Service]:
    """Read ``spec/services.json`` (a JSON list of services)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ServiceError(f"service catalog not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ServiceError(f"service catalog {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ServiceError(f"service catalog {path} must be a JSON list")
    services = [Service.from_dict(item) for item in data]
    seen: set[str] = set()
    for svc in services:
        if svc.key in seen:
            raise ServiceError(f"duplicate service key {svc.key!r} in {path}")
        seen.add(svc.key)
    return services


def load_service_json(path: Path, key: str | None = None) -> Service:
    """Read a custom service definition: one object, or a list (then ``key`` picks the entry)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ServiceError(f"service file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ServiceError(f"service file {path} is not valid JSON: {exc}") from exc
    if isinstance(data, list):
        matches = [item for item in data if isinstance(item, dict) and item.get("key") == key]
        if not matches:
            raise ServiceError(f"service {key!r} not found in {path}")
        data = matches[0]
    svc = Service.from_dict(data)
    if key is not None and svc.key != key:
        raise ServiceError(f"service file {path} defines {svc.key!r}, not {key!r}")
    return svc


def find_service(key: str, catalog_path: Path) -> Service:
    """Look up ``key`` in the catalog; ``demo`` is built in."""
    if key == DEMO.key:
        return DEMO
    for svc in load_catalog(catalog_path):
        if svc.key == key:
            return svc
    raise ServiceError(f"unknown service {key!r}; run 'sdk-kit list' or pass --service-json")
