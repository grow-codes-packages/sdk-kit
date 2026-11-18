"""Exercise the generated root Makefile with a fake ``docker`` and fake language Makefiles."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from sdk_kit.generate import new
from sdk_kit.kit import Kit
from sdk_kit.services import Service
from tests.conftest import STUB_SERVICES, write

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="GNU make not installed")

FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$DOCKER_LOG"
case "$*" in
  *" run "*) case "$*" in *test-${FAIL_LANG:-none}*) exit 3 ;; esac ;;
esac
exit 0
"""


@pytest.fixture
def repo(kit: Kit, tmp_path: Path) -> Path:
    # Use the real root Makefile with the stub kit.
    real = Path(__file__).resolve().parent.parent / "template" / "common" / "Makefile"
    shutil.copy(real, kit.template / "common" / "Makefile")
    dest = tmp_path / "beta"
    new(kit, Service.from_dict(STUB_SERVICES[1]), dest)
    return dest


def make(repo: Path, tmp_path: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    bindir = tmp_path / "fakebin"
    write(bindir / "docker", FAKE_DOCKER, mode=0o755)
    full_env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "DOCKER_LOG": str(tmp_path / "docker.log"),
        **env,
    }
    return subprocess.run(
        ["make", "--no-print-directory", *args],
        cwd=repo,
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )


def docker_calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "docker.log"
    return log.read_text().splitlines() if log.exists() else []


def test_delegates_to_language_makefiles(repo: Path, tmp_path: Path) -> None:
    result = make(repo, tmp_path, "test", "LANGS=go python")
    assert result.returncode == 0, result.stderr
    assert "==> go: make test" in result.stdout and "python test" in result.stdout
    assert "typescript" not in result.stdout


def test_test_docker_runs_and_always_cleans_up(repo: Path, tmp_path: Path) -> None:
    locks = tmp_path / "locks"
    locks.mkdir()
    result = make(
        repo,
        tmp_path,
        "test-docker",
        "LANGS=go python rust",
        SDK_DOCKER_LOCK_DIR=str(locks),
        FAIL_LANG="python",
    )
    assert result.returncode != 0
    assert "docker integration failed for: python" in result.stdout
    calls = docker_calls(tmp_path)
    runs = [c for c in calls if " run --rm --build test-" in c]
    downs = [c for c in calls if " down -v --remove-orphans" in c]
    assert len(runs) == 3 and len(downs) == 3
    projects = [c.split(" -p ")[1].split()[0] for c in runs]
    assert len(set(projects)) == 3
    assert all(p.startswith("beta-obs-") for p in projects)
    for lang, project in zip(("go", "python", "rust"), projects, strict=True):
        assert f"--profile {lang}" in next(c for c in runs if project in c)
        assert any(project in c for c in downs)
    assert any(locks.glob("sdk-docker-*.lock"))


def test_test_docker_without_lock_dir(repo: Path, tmp_path: Path) -> None:
    result = make(repo, tmp_path, "test-docker", "LANGS=java", SDK_DOCKER_LOCK_DIR=str(tmp_path / "nolocks"))
    assert result.returncode == 0, result.stderr + result.stdout
    assert "docker integration passed: java" in result.stdout
    calls = docker_calls(tmp_path)
    assert any("-f docker/compose.yml" in c and "test-java" in c for c in calls)
    assert any("down -v" in c for c in calls)


def test_test_docker_waits_when_all_locks_busy(repo: Path, tmp_path: Path) -> None:
    if shutil.which("flock") is None:
        pytest.skip("flock not installed")
    locks = tmp_path / "locks"
    locks.mkdir()
    holders = [
        subprocess.Popen(["flock", str(locks / f"sdk-docker-{n}.lock"), "sleep", "2"]) for n in range(1, 5)
    ]
    try:
        for n in range(1, 5):  # wait until every lock is really held
            lock = str(locks / f"sdk-docker-{n}.lock")
            while subprocess.run(["flock", "-n", "-E", "9", lock, "true"], check=False).returncode != 9:
                pass
        result = make(repo, tmp_path, "test-docker", "LANGS=go", SDK_DOCKER_LOCK_DIR=str(locks))
    finally:
        for proc in holders:
            proc.wait()
    assert result.returncode == 0, result.stderr + result.stdout
    assert "all Docker locks busy" in result.stdout
