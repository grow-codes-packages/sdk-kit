"""Content rules for real template files (rendered for the demo service with every category)."""

from __future__ import annotations

import re

import pytest

from sdk_kit import keep
from sdk_kit.kit import Kit
from sdk_kit.render import RenderedFile, render
from sdk_kit.services import DEMO
from tests.conftest import REPO_ROOT


@pytest.fixture(scope="module")
def files() -> dict[str, RenderedFile]:
    return render(Kit(REPO_ROOT), DEMO)


def text(files: dict[str, RenderedFile], path: str) -> str:
    return files[path].data.decode("utf-8")


def job(workflow: str, name: str) -> str:
    """The YAML block of one job (two-space indented key up to the next job)."""
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)", workflow, re.M | re.S)
    assert match, name
    return match.group(1)


def test_pypi_publishes_even_when_another_publish_job_fails(files: dict[str, RenderedFile]) -> None:
    release = text(files, ".github/workflows/release.yml")
    pypi = job(release, "pypi")
    assert "needs: [release, pypi-dist]" in pypi
    assert (
        "if: ${{ !cancelled() && (needs.release.outputs.python-release-created == 'true' "
        "|| needs.pypi-dist.outputs.found == 'true') }}"
    ) in pypi
    assert "skip-existing: true" in pypi
    gate = job(release, "pypi-dist")
    assert "if: ${{ !cancelled() && needs.release.result == 'failure' }}" in gate
    assert "actions: read" in gate
    assert "artifacts?name=python-dist" in gate


def test_python_release_flag_comes_from_release_please_job() -> None:
    reusable = (REPO_ROOT / ".github" / "workflows" / "release-packages.yml").read_text(encoding="utf-8")
    assert "value: ${{ jobs.release-please.outputs.python-release-created }}" in reusable
    assert "name: python-dist" in job(reusable, "python-build")


EXPECTED_REGIONS = {
    "docs/configuration.md": ["service-settings", "examples"],
    "docs/troubleshooting.md": ["connect", "authentication", "service"],
    "docs/client.md": ["functions", "examples", "service"],
    "AGENTS.md": ["service-specifics"],
    "java/pom.xml": [
        "description",
        "properties",
        "dependency-management",
        "dependencies",
        "compiler-args",
        "plugins",
    ],
}


@pytest.mark.parametrize("path", sorted(EXPECTED_REGIONS))
def test_generated_files_have_service_keep_regions(files: dict[str, RenderedFile], path: str) -> None:
    item = files[path]
    assert item.generated
    assert [r.name for r in keep.parse(text(files, path), path)] == EXPECTED_REGIONS[path]


@pytest.mark.parametrize(
    "path", ["docs/configuration.md", "docs/troubleshooting.md", "docs/client.md", "AGENTS.md"]
)
def test_generated_docs_assume_no_token_outside_keep_regions(
    files: dict[str, RenderedFile], path: str
) -> None:
    shared = keep.strip(text(files, path))
    assert "GROW_DEMO_TOKEN" not in shared
    assert not re.search(r"`token`|\.token\(|token=|Token:", shared), path


def test_client_docs_state_the_closed_client_rule(files: dict[str, RenderedFile]) -> None:
    assert "Any call on a closed client fails with `CANCELLED`" in text(files, "docs/client.md")
