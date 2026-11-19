from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sdk_kit import __version__
from sdk_kit.cli import main
from sdk_kit.kit import Kit
from tests.conftest import REPO_ROOT, STUB_SERVICES


def run(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(list(args), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"sdk-kit {__version__}"


def test_list(kit: Kit) -> None:
    code, out, _ = run("--kit-root", str(kit.root), "list")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].split() == ["KEY", "SERVICE", "PKG", "CATEGORIES", "IMAGE"]
    assert lines[1].split() == [
        "alpha-secrets",
        "AlphaSecrets",
        "alphasecrets",
        "secrets",
        "alpha/alpha:1.2.3",
    ]
    assert lines[2].split()[3] == "logging,tracing"
    assert lines[-1].split()[0] == "demo"


def test_list_real_catalog() -> None:
    code, out, _ = run("list")
    assert code == 0
    assert len(out.splitlines()) == 1 + 17 + 1


def test_new_sync_check_flow(kit: Kit, tmp_path: Path) -> None:
    dest = tmp_path / "beta-obs"
    code, out, err = run("--kit-root", str(kit.root), "new", "beta-obs", "--dest", str(dest))
    assert code == 0, err
    assert "generated beta-obs (logging, tracing)" in out
    code, out, _ = run("check", "--dest", str(dest))
    assert (code, out) == (0, "check passed\n")
    code, out, _ = run("--kit-root", str(kit.root), "sync", "--dest", str(dest))
    assert code == 0
    assert "0 updated, 0 created, 0 removed" in out
    tpl = kit.template / "go" / "src" / "core" / "errors.go"
    tpl.write_text(tpl.read_text() + "// v2\n")
    code, out, _ = run("--kit-root", str(kit.root), "sync", "--dest", str(dest), "--dry-run")
    assert code == 0
    assert "would update: go/src/core/errors.go" in out and "(dry run)" in out
    local = dest / "rust" / "src" / "core" / "errors.rs"
    local.write_text(local.read_text() + "// local\n")
    tpl_rs = kit.template / "rust" / "src" / "core" / "errors.rs"
    tpl_rs.write_text(tpl_rs.read_text() + "// v2\n")
    code, out, _ = run("--kit-root", str(kit.root), "sync", "--dest", str(dest), "--categories", "logging")
    assert code == 1
    assert "update: go/src/core/errors.go" in out
    assert "SKIPPED (locally modified; --force overwrites): rust/src/core/errors.rs" in out
    assert "remove: go/src/tracing_setup.go" in out
    code, out, _ = run("--kit-root", str(kit.root), "sync", "--dest", str(dest), "--force")
    assert code == 0
    (dest / "go" / "src" / "core" / "errors.go").write_text("// mine now\n")
    code, out, _ = run("--kit-root", str(kit.root), "sync", "--dest", str(dest))
    assert "kept (header removed, now service-owned): go/src/core/errors.go" in out
    (dest / "LICENSE").unlink()
    code, out, _ = run("check", "--dest", str(dest), "--key", "beta-obs")
    assert code == 1
    assert "FAIL LICENSE missing" in out and "check failed: 1 problem(s)" in out


def test_new_categories_and_default_dest(kit: Kit, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    code, _, err = run("--kit-root", str(kit.root), "new", "demo", "--categories", "secrets,tracing")
    assert code == 0, err
    data = json.loads((tmp_path / "demo" / ".sdk-kit.json").read_text())
    assert data["categories"] == ["secrets", "tracing"]


def test_new_service_json_and_sync_service_json(kit: Kit, tmp_path: Path) -> None:
    spec = tmp_path / "svc.json"
    spec.write_text(json.dumps([{**STUB_SERVICES[0], "key": "gamma", "service": "Gamma", "pkg": "gamma"}]))
    dest = tmp_path / "gamma"
    code, _, err = run(
        "--kit-root", str(kit.root), "new", "gamma", "--service-json", str(spec), "--dest", str(dest),
        "--package-version", "2.0.0",
    )  # fmt: skip
    assert code == 0, err
    assert json.loads((dest / ".sdk-kit.json").read_text())["packageVersion"] == "2.0.0"
    code, _, err = run("--kit-root", str(kit.root), "sync", "--dest", str(dest), "--service-json", str(spec))
    assert code == 0, err


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["new", "nope"], "unknown service 'nope'"),
        (["new", "demo", "--categories", "metrics"], "unknown category: metrics"),
        (["sync", "--dest", "/nonexistent-sdk-kit-dir"], "has no .sdk-kit.json"),
    ],
)
def test_errors_exit_2(kit: Kit, args: list[str], message: str) -> None:
    code, _, err = run("--kit-root", str(kit.root), *args)
    assert code == 2
    assert err.startswith("sdk-kit: error: ") and message in err


def test_new_refuses_non_empty(kit: Kit, tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "f").write_text("f")
    code, _, err = run("--kit-root", str(kit.root), "new", "demo", "--dest", str(tmp_path / "x"))
    assert code == 2 and "--force" in err


def test_launcher_and_module(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHON"] = sys.executable
    result = subprocess.run(
        [str(REPO_ROOT / "bin" / "sdk-kit"), "--version"],
        capture_output=True, text=True, env=env, cwd=tmp_path, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"sdk-kit {__version__}"
    result = subprocess.run(
        [sys.executable, "-m", "sdk_kit", "list"],
        capture_output=True, text=True, cwd=REPO_ROOT, check=False,
    )  # fmt: skip
    assert result.returncode == 0 and "openbao" in result.stdout
