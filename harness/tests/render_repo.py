#!/usr/bin/env python3
"""Lay out the docker/ folder of a generated repository the way the generator does it
(harness/GENERATOR_NOTES.md), without needing the generator. Used by the harness tests.

usage: render_repo.py DEST KEY        KEY = demo | aws-secrets-manager | aws-cloudwatch-logs |
                                            datadog-logs | better-stack-logs | <any catalog key>
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]

# Docker variants: which sdk-kit files replace the template's service-owned docker files.
#   "files": {source in sdk-kit: destination in the repo}
VARIANTS: dict[str, dict[str, str]] = {
    "demo": {
        "demo/server.py": "docker/demo/server.py",
        "demo/Dockerfile": "docker/demo/Dockerfile",
        "demo/.dockerignore": "docker/demo/.dockerignore",
        "demo/compose.service.yml": "docker/compose.service.yml",
        "demo/bootstrap/bootstrap.sh": "docker/bootstrap/bootstrap.sh",
    },
    "moto": {
        "harness/moto/compose.service.yml": "docker/compose.service.yml",
        "harness/moto/bootstrap.py": "docker/bootstrap/bootstrap.py",
    },
    "fakeintake": {
        "harness/fakeintake/compose.service.yml": "docker/compose.service.yml",
        "harness/fakeintake/bootstrap.sh": "docker/bootstrap/bootstrap.sh",
        "harness/fakeintake/fakeintake.py": "docker/harness/fakeintake.py",
    },
    "betterstack-stub": {
        "harness/betterstack-stub/stub.py": "docker/betterstack-stub/stub.py",
        "harness/betterstack-stub/sql.py": "docker/betterstack-stub/sql.py",
        "harness/betterstack-stub/msgpack_decode.py": "docker/betterstack-stub/msgpack_decode.py",
        "harness/betterstack-stub/otlp.py": "docker/betterstack-stub/otlp.py",
        "harness/betterstack-stub/Dockerfile": "docker/betterstack-stub/Dockerfile",
        "harness/betterstack-stub/.dockerignore": "docker/betterstack-stub/.dockerignore",
        "harness/betterstack-stub/compose.service.yml": "docker/compose.service.yml",
        "harness/betterstack-stub/bootstrap.sh": "docker/bootstrap/bootstrap.sh",
    },
}
KEY_VARIANT = {
    "demo": "demo",
    "aws-secrets-manager": "moto",
    "aws-cloudwatch-logs": "moto",
    "datadog-logs": "fakeintake",
    "better-stack-logs": "betterstack-stub",
}
# Numeric port the service listens on inside the compose network (GROW_<KEY>_URL).
PORT_OVERRIDE = {"demo": "8080", "aws-secrets-manager": "5000", "aws-cloudwatch-logs": "5000",
                 "datadog-logs": "80", "better-stack-logs": "8080"}  # fmt: skip
IMAGE_OVERRIDE = {"demo": "grow-sdk-demo-service:local"}


def tokens_for(key: str) -> dict[str, str]:
    services = {s["key"]: s for s in json.loads((KIT / "spec/services.json").read_text())}
    if key == "demo":
        entry = {"keyUpper": "DEMO", "keySnake": "demo", "display": "Demo", "image": "", "port": ""}
    else:
        entry = services[key]
    port = PORT_OVERRIDE.get(key) or re.match(r"\d*", str(entry["port"])).group(0)  # type: ignore[union-attr]
    return {
        "__KEY_UPPER__": entry["keyUpper"],
        "__KEY_SNAKE__": entry["keySnake"],
        "__SDK_KIT_VERSION__": "0.0.0-test",
        "__DISPLAY__": entry["display"],
        "__IMAGE__": IMAGE_OVERRIDE.get(key, entry["image"]),
        "__PORT__": port,
        "__KEY__": key,
    }


def render(src: Path, dst: Path, tokens: dict[str, str]) -> None:
    text = src.read_text()
    for token, value in tokens.items():
        text = text.replace(token, value)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text)
    shutil.copymode(src, dst)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write(__doc__ or "")
        return 2
    dest, key = Path(argv[0]), argv[1]
    tokens = tokens_for(key)
    common = KIT / "template/common/docker"
    for src in sorted(common.rglob("*")):
        if src.is_file():
            render(src, dest / "docker" / src.relative_to(common), tokens)
    variant = KEY_VARIANT.get(key)
    if variant:
        for src, dst in VARIANTS[variant].items():
            render(KIT / src, dest / dst, tokens)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
