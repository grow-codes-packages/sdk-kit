"""Command line interface: ``sdk-kit new | sync | list | check``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from sdk_kit import __version__
from sdk_kit.check import check
from sdk_kit.generate import GenerateError, Manifest, new, sync
from sdk_kit.kit import Kit, locate
from sdk_kit.render import RenderError
from sdk_kit.services import (
    DEFAULT_PACKAGE_VERSION,
    DEMO,
    Service,
    ServiceError,
    find_service,
    load_catalog,
    load_service_json,
    normalize_categories,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdk-kit",
        description="Generate and maintain the Grow Codes open-source service SDK repositories.",
    )
    parser.add_argument("--version", action="version", version=f"sdk-kit {__version__}")
    parser.add_argument(
        "--kit-root",
        metavar="DIR",
        help="sdk-kit data root with template/, conformance/ and spec/ (default: this checkout)",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p_new = sub.add_parser("new", help="generate a new service SDK repository")
    p_new.add_argument("key", help="service key from spec/services.json, or 'demo'")
    p_new.add_argument("--dest", metavar="DIR", help="target directory (default: ./<key>)")
    p_new.add_argument(
        "--categories",
        nargs="+",
        metavar="CATEGORY",
        help="override the service categories (secrets logging tracing auth; commas also work)",
    )
    p_new.add_argument("--service-json", metavar="FILE", help="custom service definition (JSON)")
    p_new.add_argument(
        "--package-version",
        default=DEFAULT_PACKAGE_VERSION,
        help=f"initial package version (default {DEFAULT_PACKAGE_VERSION})",
    )
    p_new.add_argument("--force", action="store_true", help="write into a non-empty directory")

    p_sync = sub.add_parser("sync", help="refresh the sdk-kit generated files of a repository")
    p_sync.add_argument("--dest", metavar="DIR", default=".", help="repository (default: .)")
    p_sync.add_argument("--categories", nargs="+", metavar="CATEGORY", help="change the categories")
    p_sync.add_argument("--service-json", metavar="FILE", help="custom service definition (JSON)")
    p_sync.add_argument("--force", action="store_true", help="also overwrite locally modified files")
    p_sync.add_argument("--dry-run", action="store_true", help="report only, write nothing")

    sub.add_parser("list", help="list the services of spec/services.json")

    p_check = sub.add_parser("check", help="verify a generated repository (used by CI)")
    p_check.add_argument("--dest", metavar="DIR", default=".", help="repository (default: .)")
    p_check.add_argument("--key", help="service key (default: from .sdk-kit.json)")
    return parser


def _service(kit: Kit, key: str, service_json: str | None) -> Service:
    if service_json:
        return load_service_json(Path(service_json), key)
    return find_service(key, kit.services)


def _cmd_new(kit: Kit, args: argparse.Namespace, out: TextIO) -> int:
    svc = _service(kit, args.key, args.service_json)
    if args.categories:
        svc = svc.with_categories(normalize_categories(args.categories))
    dest = Path(args.dest) if args.dest else Path.cwd() / svc.key
    written = new(kit, svc, dest, force=args.force, package_version=args.package_version)
    out.write(
        f"generated {svc.key} ({', '.join(svc.categories)}) in {dest}: {len(written)} files\n"
        f"next: cd {dest} && make build test\n"
    )
    return 0


def _cmd_sync(kit: Kit, args: argparse.Namespace, out: TextIO) -> int:
    dest = Path(args.dest)
    override = (
        load_service_json(Path(args.service_json), Manifest.load(dest).key) if args.service_json else None
    )
    categories = normalize_categories(args.categories) if args.categories else None
    report = sync(kit, dest, force=args.force, dry_run=args.dry_run, service=override, categories=categories)
    prefix = "would " if args.dry_run else ""
    sections = (
        (f"{prefix}update", report.updated),
        (f"{prefix}create", report.created),
        (f"{prefix}remove", report.removed),
        (f"{prefix}adopt (unedited service copy, now generated)", report.adopted),
        ("kept (header removed, now service-owned)", report.owned),
        ("SKIPPED (locally modified; --force overwrites)", report.modified),
        ("SKIPPED (keep region with content no longer in the template; --force drops it)", report.dropped),
    )
    for title, paths in sections:
        for path in paths:
            out.write(f"{title}: {path}\n")
    updated = len(report.updated) + len(report.adopted)
    out.write(
        f"sync {'(dry run) ' if args.dry_run else ''}done: {updated} updated, "
        f"{len(report.created)} created, {len(report.removed)} removed, "
        f"{len(report.unchanged)} unchanged, {len(report.modified) + len(report.dropped)} skipped\n"
    )
    return 1 if report.conflicts else 0


def _cmd_list(kit: Kit, out: TextIO) -> int:
    services = [*load_catalog(kit.services), DEMO]
    rows = [("KEY", "SERVICE", "PKG", "CATEGORIES", "IMAGE")]
    rows += [(s.key, s.service, s.pkg, ",".join(s.categories), s.image) for s in services]
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    for row in rows:
        cells = [cell.ljust(width) for cell, width in zip(row[:4], widths, strict=True)]
        out.write("  ".join([*cells, row[4]]).rstrip() + "\n")
    return 0


def _cmd_check(args: argparse.Namespace, out: TextIO) -> int:
    problems = check(Path(args.dest), args.key)
    for problem in problems:
        out.write(f"FAIL {problem}\n")
    out.write("check passed\n" if not problems else f"check failed: {len(problems)} problem(s)\n")
    return 1 if problems else 0


def main(argv: Sequence[str] | None = None, out: TextIO | None = None, err: TextIO | None = None) -> int:
    """Run the CLI; returns the process exit code (0 ok, 1 check/sync findings, 2 errors)."""
    out = out or sys.stdout
    err = err or sys.stderr
    args = _parser().parse_args(argv)
    kit = locate(args.kit_root)
    try:
        if args.command == "new":
            return _cmd_new(kit, args, out)
        if args.command == "sync":
            return _cmd_sync(kit, args, out)
        if args.command == "list":
            return _cmd_list(kit, out)
        return _cmd_check(args, out)
    except (ServiceError, RenderError, GenerateError, OSError) as exc:
        err.write(f"sdk-kit: error: {exc}\n")
        return 2


def main_entry() -> None:  # pragma: no cover - thin console-script wrapper
    """Console-script entry point."""
    sys.exit(main())
