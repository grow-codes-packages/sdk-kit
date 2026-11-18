"""Secrets conformance scenarios against the in-memory providers (sync and async)."""

from __future__ import annotations

from typing import Any

import pytest

from grow___KEY_SNAKE__.testing import (
    AsyncInMemorySecretsProvider,
    ConformanceRunner,
    InMemorySecretsProvider,
    assert_scenario,
    pytest_params,
)

CAPABILITIES = {"write", "delete", "versions"}


@pytest.mark.parametrize("scenario", pytest_params(categories=["secrets"]))
def test_secrets_scenarios_sync(scenario: dict[str, Any]) -> None:
    runner = ConformanceRunner(
        {"secrets": lambda ctx: InMemorySecretsProvider()}, capabilities=CAPABILITIES
    )
    assert_scenario(runner, scenario)


@pytest.mark.parametrize("scenario", pytest_params(categories=["secrets"]))
def test_secrets_scenarios_async(scenario: dict[str, Any]) -> None:
    runner = ConformanceRunner(
        {"secrets": lambda ctx: AsyncInMemorySecretsProvider()}, capabilities=CAPABILITIES
    )
    assert_scenario(runner, scenario)


def test_secrets_scenarios_skip_without_capabilities() -> None:
    runner = ConformanceRunner({"secrets": lambda ctx: InMemorySecretsProvider()})
    report = runner.run()
    assert report.ok, report.summary()
    assert {r.id for r in report.passed} == {"secrets.missing"}
    missing = next(r for r in report.results if r.id == "secrets.missing")
    assert missing.steps[-1].status == "skipped"  # delete requires "delete"


def test_load_env_mapping_op() -> None:
    from grow___KEY_SNAKE__.testing import runner as r

    provider = InMemorySecretsProvider()
    provider.set("m/a", "1")
    doc = {
        "id": "secrets.mapping",
        "category": "secrets",
        "steps": [
            {"op": "loadEnv", "args": {"mapping": {"X_A": "m/a"}}, "expect": {"count": 1}},
            {"op": "getAll", "args": {"path": "m/"}, "expect": {"count": 1}},
        ],
    }
    result = r.ConformanceRunner({"secrets": lambda ctx: provider}).run_scenario(doc)
    assert result.status == "passed", result.reason
