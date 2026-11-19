"""Secrets helpers on any provider; shown with the in-memory provider from ``testing``."""

from __future__ import annotations

import time

import grow___KEY_SNAKE__ as sdk
from grow___KEY_SNAKE__.testing import InMemorySecretsProvider


def connect_to_database(password: str) -> None:
    """Stand-in for real code that needs the plain secret."""
    assert password


def main() -> None:
    provider = InMemorySecretsProvider()  # use the service's provider in real code
    provider.set("app/db-password", "s3cr3t")
    provider.set("app/port", "5432")
    provider.set("app/features", {"beta": True})

    cache = sdk.SecretCache(provider, ttl_s=30, stale_while_revalidate_s=10)
    password = cache.require("app/db-password")  # a SecretValue: str()/repr() print [REDACTED]
    connect_to_database(password.reveal())  # reveal() only where the plain value is needed
    print(cache.get_number("app/port"), cache.get_json("app/features"))
    print(cache.stats())

    environ: dict[str, str] = {}
    print(provider.load_env("app/", prefix="APP_", environ=environ))  # names only

    handle = provider.watch(
        "app/port", 0.1, lambda new, old: print("port changed:", new and new.reveal())
    )
    provider.set("app/port", "6543")
    time.sleep(0.3)
    handle.stop()


if __name__ == "__main__":
    main()
