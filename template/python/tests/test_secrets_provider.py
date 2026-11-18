"""Secrets category: values, base providers (sync + async), load_env, watch."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

import grow___KEY_SNAKE__ as sdk
from grow___KEY_SNAKE__.testing import (
    AsyncInMemorySecretsProvider,
    InMemorySecretsProvider,
    InMemorySecretStore,
)

# --------------------------------------------------------------------------- SecretValue


def test_secret_value_redacts_and_reveals() -> None:
    value = sdk.SecretValue("hunter2-xyz", version="3")
    assert value.reveal() == "hunter2-xyz"
    assert value.reveal_bytes() == b"hunter2-xyz"
    assert value.version == "3"
    for text in (str(value), repr(value), f"{value}", f"{value:>30}", repr([value])):
        assert "hunter2" not in text
    assert str(value) == "SecretValue([REDACTED])"
    assert value == sdk.SecretValue(b"hunter2-xyz", version="3")
    assert value != sdk.SecretValue(b"hunter2-xyz", version="4")
    assert value != "hunter2-xyz"
    assert hash(value) == hash(sdk.SecretValue("hunter2-xyz", version="3"))
    assert len(value.fingerprint()) == 64


def test_secret_value_binary_and_json() -> None:
    binary = sdk.SecretValue(b"\xff\xfe")
    with pytest.raises(sdk.ValidationError):
        binary.reveal()
    assert binary.reveal_bytes() == b"\xff\xfe"
    assert sdk.SecretValue('{"a": [1, 2]}').json() == {"a": [1, 2]}
    with pytest.raises(sdk.ValidationError):
        sdk.SecretValue("not json").json()


# --------------------------------------------------------------------------- sync provider


@pytest.fixture
def provider() -> InMemorySecretsProvider:
    return InMemorySecretsProvider()


def test_set_get_and_typed_getters(provider: InMemorySecretsProvider) -> None:
    assert provider.set("app/a", "text") == "1"
    assert provider.set("app/a", "text2") == "2"
    assert provider.get("app/a", version="1").reveal() == "text"  # type: ignore[union-attr]
    assert provider.get_string("app/a") == "text2"
    provider.set("app/n", "42")
    provider.set("app/f", " -1.5e2 ")
    provider.set("app/inf", "inf")
    provider.set("app/b", "Off")
    provider.set("app/j", {"k": [1, "two"], "u": "é"})
    provider.set("app/bytes", b"\x00\x01")
    provider.set("app/list", [1, 2])
    assert provider.get_number("app/n") == 42
    assert provider.get_number("app/f") == -150.0
    assert provider.get_bool("app/b") is False
    assert provider.get_json("app/j") == {"k": [1, "two"], "u": "é"}
    assert provider.get_json("app/list") == [1, 2]
    assert provider.get("app/bytes").reveal_bytes() == b"\x00\x01"  # type: ignore[union-attr]
    for getter in (provider.get_number, provider.get_bool, provider.get_json):
        with pytest.raises(sdk.ValidationError):
            getter("app/a")
    with pytest.raises(sdk.ValidationError):
        provider.get_number("app/inf")
    for getter in (
        provider.get,
        provider.get_string,
        provider.get_json,
        provider.get_number,
        provider.get_bool,
        provider.metadata,
    ):
        assert getter("app/missing") is None  # type: ignore[operator]
    with pytest.raises(sdk.ValidationError):
        provider.set("app/bad", {1, 2})


def test_require_exists_delete(provider: InMemorySecretsProvider) -> None:
    provider.set("x", "1")
    assert provider.require("x").reveal() == "1"
    assert provider.exists("x") and not provider.exists("y")
    with pytest.raises(sdk.NotFoundError, match=r"secrets\.require y"):
        provider.require("y")
    provider.delete("x")
    with pytest.raises(sdk.NotFoundError):
        provider.delete("x")
    assert provider.get("x") is None


def test_get_many_get_all_list(provider: InMemorySecretsProvider) -> None:
    for name in ("p/b", "p/a", "p/c", "p/sub/deep", "other"):
        provider.set(name, name.upper())
    many = provider.get_many(["p/c", "p/missing", "p/a"])
    assert list(many) == ["p/c", "p/a"]
    assert {k: v.reveal() for k, v in provider.get_all("p/").items()} == {
        "p/a": "P/A",
        "p/b": "P/B",
        "p/c": "P/C",
    }
    names = [m.name for m in provider.list("p/")]
    assert names == ["p/a", "p/b", "p/c"]
    assert [m.name for m in provider.list()] == ["other"]
    meta = provider.metadata("p/a")
    assert meta is not None and meta.version == "1" and meta.versions == 1
    assert meta.created_at is not None and meta.created_at.tzinfo is not None


def test_set_options_and_versions(provider: InMemorySecretsProvider) -> None:
    provider.set("k", "v1", tags={"env": "dev"}, description="desc")
    with pytest.raises(sdk.ConflictError):
        provider.set("k", "v2", cas=0)
    assert provider.set("k", "v2", cas=1) == "2"
    meta = provider.metadata("k")
    assert meta is not None
    assert meta.tags == {"env": "dev"} and meta.extra == {"description": "desc"}
    provider.set("folder/k2", "v", path="folder")
    assert provider.get("k2", path="folder/").reveal() == "v"  # type: ignore[union-attr]
    provider.delete("k", versions=["1"])
    assert provider.get("k", version="1") is None
    assert provider.get_string("k") == "v2"
    provider.delete("k", versions=["2"])
    assert provider.get("k") is None
    provider.set("p", "a")
    provider.delete("p", versions=["1"], permanent=True)
    assert not provider.exists("p")


def test_load_env_from_path(provider: InMemorySecretsProvider) -> None:
    provider.set("run/db-password", "pw")
    provider.set("run/api.key", "k")
    provider.set("run/keep", "new")
    environ = {"APP_KEEP": "old"}
    result = provider.load_env("run/", prefix="APP_", environ=environ)
    assert result == {"APP_DB_PASSWORD": "run/db-password", "APP_API_KEY": "run/api.key"}
    assert environ == {"APP_KEEP": "old", "APP_DB_PASSWORD": "pw", "APP_API_KEY": "k"}
    result = provider.load_env("run/", prefix="APP_", environ=environ, override=True)
    assert environ["APP_KEEP"] == "new" and len(result) == 3
    assert "pw" not in repr(result)


def test_load_env_mapping_and_os_environ(
    provider: InMemorySecretsProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider.set("db/pass", "secret-pass")
    monkeypatch.delenv("GROW_TEST_DB_PASS", raising=False)
    assert provider.load_env({"GROW_TEST_DB_PASS": "db/pass"}) == {"GROW_TEST_DB_PASS": "db/pass"}
    import os

    assert os.environ["GROW_TEST_DB_PASS"] == "secret-pass"
    environ: dict[str, str] = {}
    with pytest.raises(sdk.NotFoundError):
        provider.load_env({"A": "db/pass", "B": "db/missing"}, environ=environ)
    assert environ == {}  # nothing set when one secret is missing


def test_env_var_name() -> None:
    assert sdk.env_var_name("a/b/c-d", "a/b/", "X_") == "X_C_D"
    assert sdk.env_var_name("/lead", None, "") == "LEAD"
    assert sdk.env_var_name("plain", "other/", "") == "PLAIN"


def test_provider_protocol_conformance(provider: InMemorySecretsProvider) -> None:
    assert isinstance(provider, sdk.SecretsProvider)
    assert isinstance(AsyncInMemorySecretsProvider(), sdk.AsyncSecretsProvider)
    assert isinstance(sdk.SecretCache(provider), sdk.SecretsProvider)


# --------------------------------------------------------------------------- watch


class Recorder:
    def __init__(self) -> None:
        self.changes: list[tuple[str | None, str | None]] = []
        self.errors: list[BaseException] = []
        self.event = threading.Event()

    def on_change(self, new: sdk.SecretValue | None, old: sdk.SecretValue | None) -> None:
        self.changes.append((new and new.reveal(), old and old.reveal()))
        self.event.set()

    def on_error(self, err: BaseException) -> None:
        self.errors.append(err)
        self.event.set()

    def wait(self, timeout: float = 2.0) -> None:
        assert self.event.wait(timeout), "no callback"
        self.event.clear()


def test_watch_detects_change_and_delete(provider: InMemorySecretsProvider) -> None:
    provider.set("w", "one")
    rec = Recorder()
    handle = provider.watch("w", 0.01, rec.on_change, on_error=rec.on_error)
    time.sleep(0.05)
    provider.set("w", "two")
    rec.wait()
    provider.delete("w")
    rec.wait()
    handle.stop()
    handle.stop()
    handle.join(1)
    assert handle.stopped
    assert rec.changes == [("two", "one"), (None, "two")]


def test_watch_unversioned_uses_hash_and_reports_errors() -> None:
    state: dict[str, Any] = {"value": sdk.SecretValue("a"), "fail": False}

    class Flaky(InMemorySecretsProvider):
        def _fetch_secret(self, name: str, opts: sdk.GetOptions) -> sdk.SecretValue | None:
            if state["fail"]:
                state["fail"] = False
                raise sdk.UnavailableError("down")
            return state["value"]

    flaky = Flaky()
    rec = Recorder()

    def bad_on_error(err: BaseException) -> None:
        rec.on_error(err)
        raise RuntimeError("error callbacks may fail")

    handle = flaky.watch("x", 0.01, rec.on_change, on_error=bad_on_error)
    time.sleep(0.05)
    state["fail"] = True
    rec.wait()
    assert isinstance(rec.errors[0], sdk.UnavailableError)
    state["value"] = sdk.SecretValue("b")
    rec.wait()
    assert rec.changes == [("b", "a")]
    flaky.close()
    handle.join(1)
    assert handle.stopped


def test_watch_on_change_errors_go_to_on_error(provider: InMemorySecretsProvider) -> None:
    provider.set("w", "1")
    rec = Recorder()

    def explode(new: Any, old: Any) -> None:
        raise ValueError("boom")

    handle = provider.watch("w", 0.01, explode, on_error=rec.on_error)
    time.sleep(0.05)
    provider.set("w", "2")
    rec.wait()
    assert isinstance(rec.errors[0], ValueError)
    handle.stop()
    # without on_error the error is swallowed
    quiet = provider.watch("w", 0.01, explode)
    time.sleep(0.03)
    provider.set("w", "3")
    time.sleep(0.05)
    quiet.stop()


def test_watch_stopped_by_owner_registry() -> None:
    registry = sdk.ResourceRegistry()

    class Owned(InMemorySecretsProvider):
        def __init__(self) -> None:
            super().__init__()
            self._owner = registry

    handle = Owned().watch("n", 0.01, lambda n, o: None)
    registry.stop_all()
    assert handle.stopped
    with pytest.raises(sdk.ValidationError):
        Owned().watch("n", 0, lambda n, o: None)


def test_watch_stop_before_change_callback() -> None:
    gate = threading.Event()
    calls: list[int] = []

    class Slow(InMemorySecretsProvider):
        n = 0

        def _fetch_secret(self, name: str, opts: sdk.GetOptions) -> sdk.SecretValue | None:
            Slow.n += 1
            if Slow.n == 2:
                gate.wait(1)
            return sdk.SecretValue(str(Slow.n))

    slow = Slow()
    handle = slow.watch("x", 0.01, lambda n, o: calls.append(1))
    time.sleep(0.05)
    handle.stop()
    gate.set()
    handle.join(1)
    assert calls == []


# --------------------------------------------------------------------------- async provider


async def test_async_provider_full_surface() -> None:
    store = InMemorySecretStore()
    p = AsyncInMemorySecretsProvider(store)
    assert await p.set("a/x", "1") == "1"
    await p.set("a/y", "yes")
    await p.set("a/z", {"j": True})
    assert (await p.get("a/x")).reveal() == "1"  # type: ignore[union-attr]
    assert await p.get_string("a/x") == "1"
    assert await p.get_number("a/x") == 1
    assert await p.get_bool("a/y") is True
    assert await p.get_json("a/z") == {"j": True}
    for getter in (p.get_string, p.get_number, p.get_bool, p.get_json, p.metadata):
        assert await getter("a/none") is None  # type: ignore[operator]
    assert (await p.require("a/x")).version == "1"
    with pytest.raises(sdk.NotFoundError):
        await p.require("a/none")
    assert await p.exists("a/x") and not await p.exists("a/none")
    assert list(await p.get_many(["a/z", "a/none", "a/x"])) == ["a/z", "a/x"]
    assert sorted(await p.get_all("a/")) == ["a/x", "a/y", "a/z"]
    assert [m.name for m in await p.list("a/")] == ["a/x", "a/y", "a/z"]
    assert (await p.metadata("a/x")) is not None
    environ: dict[str, str] = {}
    assert await p.load_env("a/", prefix="T_", environ=environ) == {
        "T_X": "a/x",
        "T_Y": "a/y",
        "T_Z": "a/z",
    }
    assert await p.load_env({"ONE": "a/x"}, environ=environ) == {"ONE": "a/x"}
    await p.delete("a/x")
    with pytest.raises(sdk.NotFoundError):
        await p.delete("a/x")
    # the sync provider sees the same store
    assert InMemorySecretsProvider(store).get_string("a/y") == "yes"


async def test_async_watch() -> None:
    p = AsyncInMemorySecretsProvider()
    await p.set("w", "1")
    changes: list[tuple[str | None, str | None]] = []
    errors: list[BaseException] = []
    changed = asyncio.Event()

    async def on_change(new: sdk.SecretValue | None, old: sdk.SecretValue | None) -> None:
        changes.append((new and new.reveal(), old and old.reveal()))
        changed.set()

    handle = p.watch("w", 0.01, on_change, on_error=errors.append)
    await asyncio.sleep(0.05)
    await p.set("w", "2")
    await asyncio.wait_for(changed.wait(), 2)
    changed.clear()
    await p.delete("w")
    await asyncio.wait_for(changed.wait(), 2)
    await p.aclose()
    await handle.wait()
    assert handle.stopped
    assert changes == [("2", "1"), (None, "2")]
    handle.stop()


async def test_async_watch_errors() -> None:
    state = {"fail": 0}
    errors: list[BaseException] = []
    got_error = asyncio.Event()

    class Flaky(AsyncInMemorySecretsProvider):
        async def _fetch_secret(self, name: str, opts: sdk.GetOptions) -> sdk.SecretValue | None:
            state["fail"] += 1
            if state["fail"] == 2:
                raise sdk.UnavailableError("down")
            return sdk.SecretValue(str(state["fail"]))

    async def on_error(err: BaseException) -> None:
        errors.append(err)
        got_error.set()

    def on_change(new: Any, old: Any) -> None:
        raise ValueError("bad callback")

    p = Flaky()
    handle = p.watch("x", 0.01, on_change, on_error=on_error)
    await asyncio.wait_for(got_error.wait(), 2)
    await asyncio.sleep(0.05)
    handle.stop()
    await handle.wait()
    assert isinstance(errors[0], sdk.UnavailableError)
    assert any(isinstance(e, ValueError) for e in errors)

    def raising_on_error(err: BaseException) -> None:
        raise RuntimeError("ignored")

    state["fail"] = 1
    h2 = Flaky().watch("x", 0.01, lambda n, o: None, on_error=raising_on_error)
    quiet = Flaky().watch("x", 0.01, lambda n, o: None)
    await asyncio.sleep(0.05)
    h2.stop()
    quiet.stop()
    await h2.wait()
    await quiet.wait()
    unstarted = sdk.AsyncWatchHandle(lambda: p.get("x"), 1, on_change)
    unstarted.stop()
    await unstarted.wait()


async def test_async_watch_owner_registry() -> None:
    registry = sdk.ResourceRegistry()

    class Owned(AsyncInMemorySecretsProvider):
        def __init__(self) -> None:
            super().__init__()
            self._owner = registry

    handle = Owned().watch("n", 0.01, lambda n, o: None)
    registry.stop_all()
    await handle.wait()
    assert handle.stopped
