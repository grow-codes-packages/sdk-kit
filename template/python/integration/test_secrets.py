"""Secrets conformance scenarios against the real service."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from factories import SECRETS_CAPABILITIES, core_client, secrets_provider

import grow___KEY_SNAKE__ as sdk
from grow___KEY_SNAKE__.testing import ConformanceRunner, assert_scenario, pytest_params


@pytest.fixture
def provider(env: dict[str, str]) -> Iterator[sdk.SecretsProvider]:
    with core_client(env) as client:
        found = secrets_provider(client)
        if found is None:
            pytest.skip("factories.secrets_provider() is not implemented for this service yet")
        yield found


@pytest.mark.parametrize("scenario", pytest_params(categories=["secrets"]))
def test_secrets_conformance(provider: sdk.SecretsProvider, scenario: dict[str, Any]) -> None:
    run_id = os.environ.get("GROW_TEST_RUN_ID", "local")
    runner = ConformanceRunner(
        {"secrets": lambda ctx: provider},
        capabilities=SECRETS_CAPABILITIES,
        prefix=f"grow-conformance/{run_id}-${{run}}/",
    )
    assert_scenario(runner, scenario)
