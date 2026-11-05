"""The configuration file, its sync into provider_configs, GET /health, and the sentinel key."""

import json
import logging
import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.config import ConfigurationError, Settings, load_settings
from app.db import Base
from app.main import create_app
from app.models import ProviderConfig
from app.providers import Providers, load_catalogue
from app.providers.catalogue import EXAMPLE_FILE
from app.providers.errors import ProviderCallError
from app.providers.fake import FakeStructuringAdapter, fake_adapters
from app.providers.interface import StructuringRequest
from app.providers.store import sync_provider_configs
from tests.contract.test_openapi_contract import load_contract, response_validator
from tests.providers.support import (
    CONTEXT,
    SENTINEL_KEY,
    Company,
    catalogue,
    config,
    make_meter,
)
from tests.redacted import redacted
from tests.support import BASE_URL, LOCAL_ORIGIN, make_client


def write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "providers.json"
    path.write_text(document if isinstance(document, str) else json.dumps(document))
    return path


def example() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(EXAMPLE_FILE.read_text(encoding="utf-8"))
    return document


def test_the_example_file_loads_with_every_configuration_disabled_and_unverified() -> None:
    cat = load_catalogue()

    assert {c.provider for c in cat.provider_configs} == {
        "anthropic",
        "google",
        "openai",
        "mistral",
        "perplexity",
    }
    assert all(not c.enabled and c.verified_at is None for c in cat.provider_configs)
    assert cat.by_id[cat.default_for("structuring")].provider == "google"
    assert cat.by_id[cat.default_for("retrieval")].provider == "perplexity"
    # No field can hold a key: the model forbids unknown fields, and none is named like one.
    assert all("key" not in name for c in example()["provider_configs"] for name in c)


def test_the_configured_file_is_used(tmp_path: Path) -> None:
    document = example()
    document["provider_configs"][0].update(enabled=True, verified_at="2026-10-20T00:00:00Z")
    path = write(tmp_path, document)

    settings = load_settings({"PROVIDER_CONFIG_FILE": str(path)})
    cat = load_catalogue(Path(settings.provider_config_file or ""))

    assert cat.by_id["gemini-flash-structuring"].approved


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda d: "{not json", "not valid JSON"),
        (lambda d: "", "not valid JSON"),
        (lambda d: d["provider_configs"][0].update(provider="acme") or d, "provider"),
        (lambda d: d["provider_configs"][0].update(api="chat") or d, "api must be one of"),
        (lambda d: d["provider_configs"][0].update(endpoint="http://x.test") or d, "endpoint"),
        (lambda d: d["provider_configs"][0].update(api_key="sk-x") or d, "api_key"),
        (
            lambda d: d["provider_configs"][0].update(verified_at="2026-10-20T00:00:00") or d,
            "verified_at",
        ),
        (lambda d: d["provider_configs"][0].pop("retention") and d, "retention"),
        (lambda d: d["roles"].update(structuring="nope") or d, "unknown configuration"),
        (
            lambda d: d["roles"].update(structuring="mistral-medium-retrieval") or d,
            "does not support",
        ),
        (lambda d: d["provider_configs"].append(d["provider_configs"][0]) or d, "duplicate"),
    ],
)
def test_an_invalid_file_stops_startup_naming_the_file(
    tmp_path: Path, change: Any, expected: str
) -> None:
    path = write(tmp_path, change(example()))

    with pytest.raises(ConfigurationError) as raised:
        load_catalogue(path)

    assert str(path) in str(raised.value) and expected in str(raised.value)
    with pytest.raises(ConfigurationError):
        create_app(
            Settings(
                database_url=None,
                allowed_origins=(LOCAL_ORIGIN,),
                provider_config_file=str(path),
                run_budget_eur=Decimal(5),
            )
        )


def test_a_missing_file_stops_startup(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="cannot be read"):
        load_catalogue(tmp_path / "absent.json")


def test_health_names_the_missing_key_settings_and_matches_the_contract() -> None:
    cat = catalogue(
        config("structurer"),
        config("searcher", "perplexity", "chat_completions"),
        retrieval="searcher",
        structuring="structurer",
    )
    environ = {"PERPLEXITY_API_KEY": SENTINEL_KEY}
    response = make_client(
        database_check=lambda: True, providers=Providers(cat, environ, meter=make_meter())
    ).get("/health")

    assert response.status_code == 200
    assert response.json()["missing_settings"] == ["GEMINI_API_KEY"]
    assert SENTINEL_KEY not in response.text
    response_validator(load_contract(), "/health", "get", 200).validate(response.json())

    environ["GEMINI_API_KEY"] = SENTINEL_KEY
    response = make_client(
        database_check=lambda: True, providers=Providers(cat, environ, meter=make_meter())
    ).get("/health")
    assert response.json()["missing_settings"] == []
    assert SENTINEL_KEY not in response.text


def test_configurations_are_synced_to_the_database(engine: Engine) -> None:
    first = catalogue(config("a"), config("b", "anthropic", "messages"))
    with Session(engine) as db:
        sync_provider_configs(db, first)
        sync_provider_configs(db, first)  # a restart changes nothing
        assert {row.id: row.enabled for row in db.query(ProviderConfig)} == {"a": True, "b": True}

        sync_provider_configs(db, catalogue(config("a", model_id="model-2")))
        rows = {row.id: row for row in db.query(ProviderConfig)}

    assert rows["a"].model_id == "model-2" and rows["a"].verified_at is not None
    assert rows["b"].enabled is False  # removed from the file: kept for usage records, disabled


def test_the_sentinel_key_never_appears_in_rows_logs_errors_or_responses(
    engine: Engine, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    cat = catalogue(config("primary"))
    environ = {"GEMINI_API_KEY": SENTINEL_KEY, "PERPLEXITY_API_KEY": SENTINEL_KEY}
    fake = FakeStructuringAdapter([RuntimeError(f"401 for key {SENTINEL_KEY}")])
    providers = Providers(cat, environ, fake_adapters(cat, fake), meter=make_meter())
    settings = Settings(
        database_url=database_url,
        allowed_origins=(LOCAL_ORIGIN,),
        admin_email="admin@example.test",
        admin_password="first-start password",
    )

    with TestClient(
        create_app(settings, engine=engine, providers=providers), base_url=BASE_URL
    ) as client:
        health = client.get("/health")
    with pytest.raises(ProviderCallError) as raised:
        providers.structuring().structure(StructuringRequest("i", redacted("d")), Company, CONTEXT)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM provider_configs")).scalars().all() == [
            "primary"
        ]
        # Every row of every table.
        dumped = repr(
            [connection.execute(table.select()).all() for table in Base.metadata.sorted_tables]
        )
    assert SENTINEL_KEY not in dumped
    assert SENTINEL_KEY not in health.text
    assert SENTINEL_KEY not in str(raised.value)
    assert SENTINEL_KEY not in caplog.text
    assert "Provider call failed" in caplog.text  # the failure is logged, without the key


SDK_PINS = {
    "anthropic": "1.13.0",
    "openai": "3.29.0",
    "google-genai": "2.30.1",
    "mistralai": "3.2.0",
    "perplexityai": "0.43.8",
}


def test_every_sdk_is_pinned_to_an_exact_version_in_the_lockfile() -> None:
    backend = Path(__file__).resolve().parents[2]
    project = tomllib.loads((backend / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((backend / "uv.lock").read_text(encoding="utf-8"))
    locked = {package["name"]: package["version"] for package in lock["package"]}

    for name, version in SDK_PINS.items():
        assert f"{name}=={version}" in project["project"]["dependencies"]
        assert locked[name] == version
