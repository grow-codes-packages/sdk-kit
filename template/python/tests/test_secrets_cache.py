"""SecretCache / AsyncSecretCache: TTL, LRU, refresh-ahead, stale-while-revalidate."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

import grow___KEY_SNAKE__ as sdk
from grow___KEY_SNAKE__.testing import (
    AsyncInMemorySecretsProvider,
    InMemorySecretsProvider,
    InMemorySecretStore,
)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Spawner:
    """Collects background refreshes so tests run them deterministically."""

    def __init__(self) -> None:
        self.jobs: list[Callable[[], None]] = []

    def __call__(self, fn: Callable[[], None]) -> None:
        self.jobs.append(fn)

    def run(self) -> None:
        jobs, self.jobs = self.jobs, []
        for job in jobs:
            job()


def make(**kw: Any) -> tuple[sdk.SecretCache, InMemorySecretsProvider, Clock, Spawner]:
    provider = InMemorySecretsProvider()
    clock, spawner = Clock(), Spawner()
    cache = sdk.SecretCache(provider, clock=clock, spawn=spawner, **kw)
    return cache, provider, clock, spawner


def test_hits_misses_and_negative_caching() -> None:
    cache, provider, clock, _ = make(ttl_s=10)
    provider.set("a", "1")
    assert cache.get_string("a") == "1"
    assert cache.get_string("a") == "1"
    assert cache.get("missing") is None
    assert cache.get("missing") is None
    assert provider.store.reads == 2
    assert cache.stats() == sdk.CacheStats(hits=2, misses=2, evictions=0, refreshes=0, size=2)
    # expiry → miss
    clock.now += 11
    provider.set("a", "2")
    assert cache.get_string("a") == "2"
    assert cache.stats().misses == 3
    assert cache.exists("a") and not cache.exists("missing")
    assert list(cache.get_many(["a", "missing"])) == ["a"]
    assert cache.require("a").reveal() == "2"


def test_writes_pass_through_and_invalidate() -> None:
    cache, provider, _, _ = make()
    cache.set("k", "v1", tags={"t": "1"})
    assert cache.get_string("k") == "v1"
    cache.get("k", version="1")
    assert cache.stats().size == 2
    cache.set("k", "v2")
    assert cache.stats().size == 0
    assert cache.get_string("k") == "v2"
    cache.delete("k")
    assert cache.get("k") is None
    with pytest.raises(sdk.NotFoundError):
        cache.delete("k")
    with pytest.raises(sdk.ConflictError):
        cache.set("k", "x", cas=5)
    assert provider.metadata("k") is None
    cache.set("p/a", "1")
    assert [m.name for m in cache.list("p/")] == ["p/a"]
    assert cache.metadata("p/a") is not None
    assert cache.get_all("p/")["p/a"].reveal() == "1"
    cache.invalidate("p/a")
    cache.clear()
    assert cache.stats().size == 0


def test_lru_eviction() -> None:
    cache, provider, _, _ = make(max_entries=2)
    for name in ("a", "b", "c"):
        provider.set(name, name)
    cache.get("a")
    cache.get("b")
    cache.get("a")  # a is now most recent
    cache.get("c")  # evicts b
    stats = cache.stats()
    assert stats.evictions == 1 and stats.size == 2
    reads = provider.store.reads
    cache.get("a")
    assert provider.store.reads == reads
    cache.get("b")
    assert provider.store.reads == reads + 1


def test_refresh_ahead() -> None:
    cache, provider, clock, spawner = make(ttl_s=10, refresh_ahead_factor=0.5)
    provider.set("a", "1")
    cache.get("a")
    clock.now += 6  # past ttl * factor
    provider.set("a", "2")
    assert cache.get_string("a") == "1"  # served from cache, refresh scheduled once
    assert cache.get_string("a") == "1"
    assert len(spawner.jobs) == 1
    spawner.run()
    assert cache.get_string("a") == "2"
    assert cache.stats().refreshes == 1


def test_stale_while_revalidate_and_refresh_failure() -> None:
    cache, provider, clock, spawner = make(
        ttl_s=10, refresh_ahead_factor=1.0, stale_while_revalidate_s=5
    )
    provider.set("a", "1")
    cache.get("a")
    clock.now += 12  # stale but within the window
    assert cache.get_string("a") == "1"
    assert len(spawner.jobs) == 1

    def broken(*args: Any, **kw: Any) -> None:
        raise sdk.UnavailableError("down")

    provider.get = broken  # type: ignore[method-assign]
    spawner.run()  # failure keeps the stale entry, allows another refresh
    assert cache.get_string("a") == "1"
    assert len(spawner.jobs) == 1
    clock.now += 10  # beyond ttl + swr → synchronous miss
    with pytest.raises(sdk.UnavailableError):
        cache.get("a")


def test_invalid_options_and_default_spawn() -> None:
    provider = InMemorySecretsProvider()
    for kw in (
        {"ttl_s": 0},
        {"max_entries": 0},
        {"refresh_ahead_factor": 0},
        {"stale_while_revalidate_s": -1},
    ):
        with pytest.raises(sdk.ValidationError):
            sdk.SecretCache(provider, **kw)  # type: ignore[arg-type]
    clock = Clock()
    cache = sdk.SecretCache(provider, ttl_s=10, refresh_ahead_factor=0.1, clock=clock)
    provider.set("a", "1")
    cache.get("a")
    clock.now += 5
    provider.set("a", "2")
    done = threading.Event()
    original = cache._state.store

    def store(key: Any, value: Any) -> None:
        original(key, value)
        done.set()

    cache._state.store = store  # type: ignore[method-assign]
    cache.get("a")
    assert done.wait(2)
    assert cache.get_string("a") == "2"


def test_cache_watch_delegates() -> None:
    cache, provider, _, _ = make()
    provider.set("w", "1")
    seen: list[str | None] = []
    event = threading.Event()

    def on_change(new: sdk.SecretValue | None, old: sdk.SecretValue | None) -> None:
        seen.append(new.reveal() if new else None)
        event.set()

    handle = cache.watch("w", 0.01, on_change)
    time.sleep(0.05)
    provider.set("w", "2")
    assert event.wait(2)
    handle.stop()
    provider.close()
    assert seen == ["2"]


async def test_async_cache() -> None:
    store = InMemorySecretStore()
    provider = AsyncInMemorySecretsProvider(store)
    clock = Clock()
    cache = sdk.AsyncSecretCache(provider, ttl_s=10, refresh_ahead_factor=0.5, clock=clock)
    await cache.set("a", "1")
    assert await cache.get_string("a") == "1"
    assert await cache.get_string("a") == "1"
    assert store.reads == 1
    clock.now += 6
    await provider.set("a", "2")
    assert await cache.get_string("a") == "1"
    await cache.wait_refreshes()
    assert await cache.get_string("a") == "2"
    stats = cache.stats()
    assert stats.refreshes == 1 and stats.size == 1
    await cache.set("b", "x")
    assert [m.name for m in await cache.list()] == ["a", "b"]
    assert await cache.metadata("b") is not None
    await cache.delete("b")
    with pytest.raises(sdk.NotFoundError):
        await cache.delete("b")
    cache.invalidate("a")
    cache.clear()
    await cache.wait_refreshes()

    async def broken(*args: Any, **kw: Any) -> None:
        raise sdk.UnavailableError("down")

    await cache.get("a")
    clock.now += 6
    provider.get = broken  # type: ignore[method-assign]
    assert await cache.get_string("a") == "2"
    await cache.wait_refreshes()
    assert await cache.get_string("a") == "2"
    await cache.wait_refreshes()
    handle = cache.watch("a", 1, lambda n, o: None)
    handle.stop()
    await handle.wait()


async def test_async_cache_cancelled_refresh_can_be_retried() -> None:
    store = InMemorySecretStore()
    provider = AsyncInMemorySecretsProvider(store)
    clock = Clock()
    cache = sdk.AsyncSecretCache(provider, ttl_s=10, refresh_ahead_factor=0.5, clock=clock)
    await cache.set("a", "1")
    await cache.get("a")
    entered = asyncio.Event()

    async def hanging(*args: Any, **kw: Any) -> None:
        entered.set()
        await asyncio.Event().wait()  # cancelled below (plain asyncio.CancelledError)

    real_get = provider.get
    provider.get = hanging  # type: ignore[method-assign]
    clock.now += 6
    assert await cache.get_string("a") == "1"  # schedules a background refresh
    await asyncio.wait_for(entered.wait(), 5)
    for task in list(cache._tasks):
        task.cancel()
    await cache.wait_refreshes()
    provider.get = real_get  # type: ignore[method-assign]
    await provider.set("a", "2")
    assert await cache.get_string("a") == "1"  # the cancelled refresh released the entry
    await cache.wait_refreshes()
    assert await cache.get_string("a") == "2"
