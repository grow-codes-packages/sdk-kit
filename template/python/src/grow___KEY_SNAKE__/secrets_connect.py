"""Connector used by ``load_config()``.

Service-owned: generated once by sdk-kit, then maintained in this repository. It builds a client
from the ``GROW_SECRETS_*`` bootstrap and the package's own environment variables, logs in when
the service needs it, and returns the provider to read the config keys from.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._core.errors import UnsupportedError
from ._secrets.load_config import SecretsBootstrap, SecretsConnection
from .client import __SERVICE__Client


def connect_secrets(bootstrap: SecretsBootstrap, env: Mapping[str, str]) -> SecretsConnection:
    """Build ``__SERVICE__Client.from_env()`` and return its ``secrets()`` provider.

    Services that log in (AppRole, ...) replace this function.
    """
    overrides: dict[str, Any] = {} if bootstrap.addr is None else {"url": bootstrap.addr}
    client = __SERVICE__Client.from_env(env, **overrides)
    factory = getattr(client, "secrets", None) or getattr(client, "secrets_provider", None)
    if not callable(factory):
        client.close()
        raise UnsupportedError("load_config: __SERVICE__Client has no secrets() provider")
    return SecretsConnection(provider=factory(), close=client.close)
