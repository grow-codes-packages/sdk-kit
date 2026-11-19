"""Factories the integration suite and the conformance runner use (owned by this repository).

sdk-kit generates this file once. Replace the bodies when the service needs more setup (extra
credentials from /bootstrap/env, namespaces, a provider built on the client …) and keep the
capability sets honest: every capability left out skips scenarios, and each skip must be
explained in docs/compatibility.md.
"""

from __future__ import annotations

from collections.abc import Mapping
# @sdk-kit:if any(logging,tracing)
from typing import Any
# @sdk-kit:endif

import grow___KEY_SNAKE__ as sdk

URL_VAR = "GROW___KEY_UPPER___URL"

#: Capabilities of the deployment under test for the core scenarios ("version" = serverVersion,
#: "auth" = the deployment rejects a wrong token; drop it for services without authentication).
CORE_CAPABILITIES: set[str] = {"version", "auth"}


def core_client(env: Mapping[str, str]) -> sdk.__SERVICE__Client:
    """A client configured from the test environment (URL, token, … from /bootstrap/env)."""
    return sdk.__SERVICE__Client.from_env(env)


def async_core_client(env: Mapping[str, str]) -> sdk.Async__SERVICE__Client:
    return sdk.Async__SERVICE__Client.from_env(env)
# @sdk-kit:if secrets


#: Capabilities for the secrets scenarios: write, delete, versions.
SECRETS_CAPABILITIES: set[str] = {"write", "delete", "versions"}


def secrets_provider(client: sdk.__SERVICE__Client) -> sdk.SecretsProvider | None:
    """The service's secrets provider on top of ``client``; ``None`` skips the secrets suite.

    Replace with the real provider, e.g. ``return client.kv``.
    """
    return None
# @sdk-kit:endif
# @sdk-kit:if logging


#: Capabilities for the logging scenarios: query, tail, streams, labels.
LOGGING_CAPABILITIES: set[str] = {"query"}


def logging_target(env: Mapping[str, str], scenario: Mapping[str, Any]) -> Any | None:
    """A ``testing.LoggingTarget(client, query)`` for one scenario; ``None`` skips the suite.

    Apply ``scenario.get("batchOptions")`` when building the log client.
    """
    return None
# @sdk-kit:endif
# @sdk-kit:if tracing


#: Capabilities for the tracing scenarios: query, services, dependencies.
TRACING_CAPABILITIES: set[str] = {"query", "services"}


def tracing_target(env: Mapping[str, str], scenario: Mapping[str, Any]) -> Any | None:
    """A ``testing.TracingTarget(handle, query)`` for one scenario; ``None`` skips the suite."""
    return None
# @sdk-kit:endif
