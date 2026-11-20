"""Connector of ``load_config()`` (service-owned: generated once by sdk-kit)."""

from __future__ import annotations

import grow___KEY_SNAKE__ as sdk
from grow___KEY_SNAKE__.secrets_connect import connect_secrets


def test_connect_secrets_without_io() -> None:
    try:
        connection = connect_secrets(sdk.SecretsBootstrap(addr="http://127.0.0.1:1"), {})
    except (sdk.UnsupportedError, sdk.ConfigError):
        return
    assert callable(connection.provider.get_all)
    if connection.close is not None:
        connection.close()
