from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdk_kit import __version__
from sdk_kit.services import (
    DEMO,
    SERVICE_CATEGORIES,
    Service,
    ServiceError,
    find_service,
    load_catalog,
    load_service_json,
    lower_camel,
    normalize_categories,
)
from tests.conftest import REPO_ROOT, STUB_SERVICES


def test_normalize_categories_orders_and_splits() -> None:
    assert normalize_categories(["tracing", "secrets"]) == ("secrets", "tracing")
    assert normalize_categories("logging, tracing") == ("logging", "tracing")
    assert normalize_categories(["tracing,logging", "logging"]) == ("logging", "tracing")
    assert normalize_categories(["auth", "secrets"]) == ("secrets", "auth")
    assert normalize_categories("auth") == ("auth",)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (["metrics"], "unknown category: metrics"),
        (["a", "b"], "unknown categories: a, b"),
        ([""], "at least one"),
    ],
)
def test_normalize_categories_errors(value: list[str], message: str) -> None:
    with pytest.raises(ServiceError, match=message):
        normalize_categories(value)


def test_lower_camel() -> None:
    assert lower_camel("OpenBao") == "openBao"
    assert lower_camel("Vault") == "vault"
    assert lower_camel("") == ""


def test_from_dict_derives_and_round_trips() -> None:
    svc = Service.from_dict({**STUB_SERVICES[0], "npm": "@grow-codes/alpha-secrets"})
    assert svc.key_snake == "alpha_secrets"
    assert svc.key_upper == "ALPHA_SECRETS"
    assert svc.extra == {"npm": "@grow-codes/alpha-secrets"}
    again = Service.from_dict(svc.to_dict())
    assert again == svc
    assert again.to_dict()["npm"] == "@grow-codes/alpha-secrets"


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"key": ""}, "misses: key"),
        ({"key": "Bad_Key"}, "invalid key"),
        ({"pkg": "no-dash"}, "invalid pkg"),
        ({"service": "lower"}, "invalid service"),
        ({"categories": ["nope"]}, "unknown category"),
    ],
)
def test_from_dict_validation(patch: dict[str, object], message: str) -> None:
    with pytest.raises(ServiceError, match=message):
        Service.from_dict({**STUB_SERVICES[0], **patch})


def test_from_dict_rejects_non_object() -> None:
    with pytest.raises(ServiceError, match="JSON object"):
        Service.from_dict(["not", "a", "dict"])  # type: ignore[arg-type]


def test_tokens_match_spec_section_0() -> None:
    svc = Service.from_dict(STUB_SERVICES[1])
    tokens = svc.tokens("1.2.3")
    assert tokens == {
        "KEY": "beta-obs",
        "KEY_SNAKE": "beta_obs",
        "KEY_UPPER": "BETA_OBS",
        "PKG": "betaobs",
        "SERVICE": "BetaObs",
        "SERVICE_LOWER": "betaObs",
        "DISPLAY": "Beta Observability",
        "VENDOR": "Beta Ltd.",
        "UPSTREAM_LICENSE": "Apache-2.0",
        "IMAGE": "beta/beta:4.5.6",
        "PORT": "4318",
        "VERSION": "1.2.3",
        "SDK_KIT_VERSION": __version__,
        "CATEGORIES": "logging,tracing",
        "ENV": "`BETA_URL`",
    }


def test_with_categories_copies() -> None:
    svc = DEMO.with_categories(("logging",))
    assert svc.categories == ("logging",)
    assert DEMO.categories == SERVICE_CATEGORIES
    assert svc.key == "demo"


def test_demo_service() -> None:
    assert DEMO.image == "sdk-kit-demo"
    assert DEMO.port == "8080"
    assert DEMO.tokens()["SERVICE_LOWER"] == "demo"


def test_load_real_catalog() -> None:
    services = load_catalog(REPO_ROOT / "spec" / "services.json")
    assert len(services) == 17
    assert {s.key for s in services} >= {"openbao", "hashicorp-vault", "jaeger", "apache-skywalking"}
    vault = next(s for s in services if s.key == "hashicorp-vault")
    assert vault.tokens()["PKG"] == "vault"
    assert vault.tokens()["KEY_UPPER"] == "HASHICORP_VAULT"


def test_load_catalog_errors(tmp_path: Path) -> None:
    with pytest.raises(ServiceError, match="not found"):
        load_catalog(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    with pytest.raises(ServiceError, match="not valid JSON"):
        load_catalog(bad)
    obj = tmp_path / "obj.json"
    obj.write_text("{}", encoding="utf-8")
    with pytest.raises(ServiceError, match="must be a JSON list"):
        load_catalog(obj)
    dup = tmp_path / "dup.json"
    dup.write_text(json.dumps([STUB_SERVICES[0], STUB_SERVICES[0]]), encoding="utf-8")
    with pytest.raises(ServiceError, match="duplicate"):
        load_catalog(dup)


def test_load_service_json(tmp_path: Path) -> None:
    one = tmp_path / "one.json"
    one.write_text(json.dumps(STUB_SERVICES[0]), encoding="utf-8")
    assert load_service_json(one).key == "alpha-secrets"
    assert load_service_json(one, "alpha-secrets").pkg == "alphasecrets"
    with pytest.raises(ServiceError, match="not 'other'"):
        load_service_json(one, "other")
    many = tmp_path / "many.json"
    many.write_text(json.dumps(STUB_SERVICES), encoding="utf-8")
    assert load_service_json(many, "beta-obs").service == "BetaObs"
    with pytest.raises(ServiceError, match="not found in"):
        load_service_json(many, "gamma")
    with pytest.raises(ServiceError, match="service file not found"):
        load_service_json(tmp_path / "nope.json")
    broken = tmp_path / "broken.json"
    broken.write_text("[", encoding="utf-8")
    with pytest.raises(ServiceError, match="not valid JSON"):
        load_service_json(broken)


def test_find_service(tmp_path: Path) -> None:
    catalog = tmp_path / "services.json"
    catalog.write_text(json.dumps(STUB_SERVICES), encoding="utf-8")
    assert find_service("demo", catalog) is DEMO
    assert find_service("beta-obs", catalog).categories == ("logging", "tracing")
    with pytest.raises(ServiceError, match="unknown service 'gamma'"):
        find_service("gamma", catalog)
