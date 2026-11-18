"""Locate the sdk-kit data: template, conformance suite, service catalog and demo server."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Kit:
    """Paths of one sdk-kit data root (a checkout, or the copy bundled in the wheel)."""

    root: Path

    @property
    def template(self) -> Path:
        return self.root / "template"

    @property
    def conformance(self) -> Path:
        return self.root / "conformance"

    @property
    def services(self) -> Path:
        return self.root / "spec" / "services.json"

    @property
    def demo(self) -> Path:
        return self.root / "demo"


def default_root() -> Path:
    """The checkout root when running from source, else the data bundled in the package."""
    checkout = PACKAGE_DIR.parent
    if (checkout / "template").is_dir():
        return checkout
    return PACKAGE_DIR / "_kit"  # pragma: no cover - only in an installed wheel


def locate(root: str | Path | None = None) -> Kit:
    """Return the kit at ``root`` (or the default one)."""
    return Kit(Path(root).resolve() if root else default_root())
