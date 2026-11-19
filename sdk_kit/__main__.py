"""Allow ``python -m sdk_kit``."""

from __future__ import annotations

import sys

from sdk_kit.cli import main

if __name__ == "__main__":  # pragma: no cover - exercised through the launcher
    sys.exit(main())
