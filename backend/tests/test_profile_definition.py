"""Profile definition (#21): schema, example, loading, startup failures, endpoint, run hash."""

import copy
import dataclasses
import json
import logging
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import Engine

from app.config import ConfigurationError, Settings, load_settings
from app.content import CONTENT_DIR, load_schema
from app.main import create_app
from app.profile_definition import EXAMPLE_FILE, load_profile_definition
from tests.auth_support import assert_requires_session, send_with_session
from tests.contract.test_auth_contract import assert_matches_contract
from tests.factories import create_session, create_user
from tests.runs_support import create_identity, get_run
from tests.support import LOCAL_ORIGIN

SCHEMA = "profile-definition.schema.json"


def example() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(EXAMPLE_FILE.read_text(encoding="utf-8"))
    return document


def write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "definition.json"
    path.write_text(document if isinstance(document, str) else json.dumps(document))
    return path


def first_field(document: dict[str, Any]) -> dict[str, Any]:
    field: dict[str, Any] = document["sections"][0]["fields"][0]
    return field


# --- schema and example ----------------------------------------------------------------------


def test_the_schema_is_published_and_valid() -> None:
    assert (CONTENT_DIR / SCHEMA).is_file()
    Draft202012Validator.check_schema(load_schema(SCHEMA))


def test_the_example_has_four_sections_and_every_kind_and_validates() -> None:
    definition = load_profile_definition()

    assert [section.id for section in definition.sections] == [
        "company_overview",
        "production_footprint",
        "certifications",
        "swot",
    ]
    assert {field.kind for field in definition.fields()} == {"fact", "assessment", "buyer"}
    assert any(field.certification for field in definition.fields())
    assert any(field.concerns_people for field in definition.fields())
    assert not Draft202012Validator(load_schema(SCHEMA)).is_valid({"sections": []})
    assert Draft202012Validator(load_schema(SCHEMA)).is_valid(example())
    assert definition.content_hash.startswith("sha256:")


def test_flags_default_to_false_and_must_be_booleans(tmp_path: Path) -> None:
    document = example()
    field = first_field(document)
    assert "concerns_people" not in field
    assert load_profile_definition(write(tmp_path, document)).fields()[0].concerns_people is False

    field["concerns_people"] = True
    field["certification"] = True
    loaded = load_profile_definition(write(tmp_path, document)).fields()[0]
    assert (loaded.concerns_people, loaded.certification) == (True, True)

    for flag in ("concerns_people", "certification"):
        broken = copy.deepcopy(document)
        first_field(broken)[flag] = "yes"
        with pytest.raises(ConfigurationError, match=f"sections/0/fields/0/{flag}"):
            load_profile_definition(write(tmp_path, broken))


def test_the_hash_follows_the_content_not_the_formatting(tmp_path: Path) -> None:
    document = example()
    reformatted = write(tmp_path, json.dumps(document, indent=4, sort_keys=True))
    assert (
        load_profile_definition(reformatted).content_hash == load_profile_definition().content_hash
    )

    first_field(document)["labels"]["en"] = "Changed"
    changed = load_profile_definition(write(tmp_path, document)).content_hash
    assert changed != load_profile_definition().content_hash


# --- invalid files stop startup ----------------------------------------------------------------


def duplicate_section(document: dict[str, Any]) -> None:
    document["sections"][1]["id"] = document["sections"][0]["id"]


def duplicate_field_in_section(document: dict[str, Any]) -> None:
    fields = document["sections"][0]["fields"]
    fields[1]["id"] = fields[0]["id"]


def duplicate_field_across_sections(document: dict[str, Any]) -> None:
    document["sections"][1]["fields"][0]["id"] = first_field(document)["id"]


def unknown_kind(document: dict[str, Any]) -> None:
    first_field(document)["kind"] = "guess"


def missing_french_label(document: dict[str, Any]) -> None:
    del first_field(document)["labels"]["fr"]


def non_english_identifier(document: dict[str, Any]) -> None:
    first_field(document)["id"] = "année"


def unknown_property(document: dict[str, Any]) -> None:
    first_field(document)["colour"] = "red"


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (duplicate_section, "duplicate section id 'company_overview'"),
        (duplicate_field_in_section, "duplicate field id 'legal_form'"),
        (duplicate_field_across_sections, "duplicate field id 'legal_form'"),
        (unknown_kind, "sections/0/fields/0/kind"),
        (missing_french_label, "sections/0/fields/0/labels"),
        (non_english_identifier, "sections/0/fields/0/id"),
        (unknown_property, "sections/0/fields/0"),
    ],
)
def test_a_schema_violation_or_duplicate_names_the_file_and_the_path(
    tmp_path: Path, mutate: Any, expected: str
) -> None:
    document = example()
    mutate(document)
    path = write(tmp_path, document)

    with pytest.raises(ConfigurationError) as raised:
        load_profile_definition(path)

    assert str(path) in str(raised.value)
    assert expected in str(raised.value)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("{not json", "not valid JSON"),
        ("", "is empty"),
        ("  \n", "is empty"),
        ("[]", "(document)"),
        ('{"sections": []}', "sections"),
    ],
)
def test_invalid_json_and_empty_files_name_the_file(
    tmp_path: Path, content: str, expected: str
) -> None:
    path = write(tmp_path, content)

    with pytest.raises(ConfigurationError) as raised:
        load_profile_definition(path)

    assert str(path) in str(raised.value)
    assert expected in str(raised.value)


def test_a_missing_file_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "absent.json"

    with pytest.raises(ConfigurationError) as raised:
        load_profile_definition(path)

    assert str(path) in str(raised.value)
    assert "cannot be read" in str(raised.value)


def test_startup_stops_on_a_bad_file_and_loads_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = write(tmp_path, "{broken")
    settings = Settings(
        database_url=None,
        allowed_origins=(LOCAL_ORIGIN,),
        profile_definition_file=str(path),
        run_budget_eur=Decimal(5),
    )

    with caplog.at_level(logging.ERROR), pytest.raises(ConfigurationError) as raised:
        create_app(settings)

    assert str(path) in str(raised.value)
    assert str(path) in caplog.text


def test_the_configured_file_is_used_and_the_example_when_absent(tmp_path: Path) -> None:
    document = example()
    first_field(document)["labels"]["en"] = "Instance label"
    path = write(tmp_path, document)

    configured = load_settings({"PROFILE_DEFINITION_FILE": str(path)})
    default = load_settings({})
    assert configured.profile_definition_file == str(path)
    assert default.profile_definition_file is None

    app = create_app(
        Settings(
            database_url=None,
            allowed_origins=(LOCAL_ORIGIN,),
            profile_definition_file=str(path),
            run_budget_eur=Decimal(5),
        )
    )
    assert app.state.profile_definition.sections[0].fields[0].labels["en"] == "Instance label"
    other = create_app(dataclasses.replace(default, run_budget_eur=Decimal(5)))
    assert other.state.profile_definition.content_hash == load_profile_definition().content_hash


# --- GET /profile-definition ---------------------------------------------------------------------


def test_the_endpoint_returns_labels_in_the_requested_language(
    client: TestClient, engine: Engine
) -> None:
    token = create_session(engine, create_user(engine).id)
    expected = load_profile_definition()

    english = send_with_session(client, "GET", "/profile-definition", token)
    french = send_with_session(client, "GET", "/profile-definition?language=fr", token)

    assert english.status_code == french.status_code == 200
    assert_matches_contract(english, "/profile-definition", "get")
    assert_matches_contract(french, "/profile-definition", "get")
    assert english.json()["hash"] == french.json()["hash"] == expected.content_hash
    assert english.json()["language"] == "en"
    assert english.json()["sections"][0]["label"] == "Company overview"
    assert french.json()["language"] == "fr"
    assert french.json()["sections"][0]["label"] == "Présentation de l'entreprise"
    people = [f for s in french.json()["sections"] for f in s["fields"] if f["concerns_people"]]
    assert [field["id"] for field in people] == ["management_team"]
    assert "extraction_hint" not in json.dumps(french.json())


def test_the_endpoint_refuses_an_unknown_language_and_needs_a_session(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)

    response = send_with_session(client, "GET", "/profile-definition?language=de", token)

    assert response.status_code == 422
    assert_matches_contract(response, "/profile-definition", "get")
    assert_requires_session(client, engine, "GET", "/profile-definition", user)


# --- the hash recorded on each run -------------------------------------------------------------


def test_a_new_run_records_the_definition_hash(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    identity_id = create_identity(engine, user.organisation_id)

    response = send_with_session(
        client, "POST", "/runs", token, json={"identity_id": str(identity_id)}
    )

    assert response.status_code == 202
    expected = load_profile_definition().content_hash
    assert response.json()["profile_definition_hash"] == expected
    assert get_run(engine, uuid.UUID(response.json()["id"])).profile_definition_hash == expected
