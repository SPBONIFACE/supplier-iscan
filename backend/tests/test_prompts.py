"""Prompt set (#55): schema, example, loading, startup failures, rendering, run hash, no leaks."""

import copy
import json
import logging
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import BaseModel
from sqlalchemy import Engine

from app.config import ConfigurationError, Settings, load_settings
from app.content import load_schema
from app.main import create_app
from app.prompts import EXAMPLE_FILE, SPECS, load_prompt_set, log_render
from app.providers.fake import FakeStructuringAdapter
from app.providers.interface import StructuringOutput, StructuringRequest
from app.providers.metering import CallContext, CallUsage, ListSink
from tests.auth_support import send_with_session
from tests.factories import create_session, create_user
from tests.providers.test_metering import providers_with
from tests.runs_support import create_identity, get_run
from tests.support import LOCAL_ORIGIN

IDS = ["identity", "retrieval", "extraction", "assessment", "fit", "recommendations"]


def example() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(EXAMPLE_FILE.read_text(encoding="utf-8"))
    return document


def write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "prompts.json"
    path.write_text(document if isinstance(document, str) else json.dumps(document))
    return path


def entry(document: dict[str, Any], prompt_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(p for p in document["prompts"] if p["id"] == prompt_id)
    return found


def settings_with(path: Path) -> Settings:
    return Settings(database_url=None, allowed_origins=(LOCAL_ORIGIN,), prompt_set_file=str(path))


def test_the_example_has_every_prompt_id_and_validates_against_the_schema() -> None:
    document = example()

    assert Draft202012Validator(load_schema("prompt-set.schema.json")).is_valid(document)
    assert [p["id"] for p in document["prompts"]] == IDS
    assert set(SPECS) == set(IDS)
    assert set(load_prompt_set().prompts) == set(IDS)
    assert {p["output_schema"] for p in document["prompts"]} == {
        "IdentityProposal",
        "RetrievalResult",
        "FieldExtraction",
        "AssessmentStatement",
    }


def test_the_setting_is_read_and_the_example_is_the_default() -> None:
    assert load_settings({}).prompt_set_file is None
    assert load_settings({"PROMPT_SET_FILE": " /x.json "}).prompt_set_file == "/x.json"


def test_a_configured_file_replaces_the_example_and_the_text_follows_the_file(
    tmp_path: Path,
) -> None:
    document = example()
    entry(document, "retrieval")["instructions"] = "ALTERNATIVE retrieval text."
    path = write(tmp_path, document)
    values = {"supplier": "Acme SA"}

    default = load_prompt_set().render("retrieval", values)
    other = load_prompt_set(path).render("retrieval", values)

    assert other.instructions == "ALTERNATIVE retrieval text."
    assert default.instructions != other.instructions
    assert other.data == default.data
    assert other.set_hash != default.set_hash
    assert create_app(settings_with(path)).state.prompt_set.content_hash == other.set_hash


def test_a_partial_file_is_not_completed_from_the_example(tmp_path: Path) -> None:
    document = example()
    document["prompts"] = [p for p in document["prompts"] if p["id"] != "fit"]

    with pytest.raises(ConfigurationError, match="prompt id 'fit' is missing"):
        load_prompt_set(write(tmp_path, document))


def duplicate(d: dict[str, Any]) -> None:
    d["prompts"].append(copy.deepcopy(entry(d, "fit")))


def wrong_output(d: dict[str, Any]) -> None:
    entry(d, "extraction")["output_schema"] = "AssessmentStatement"


def unknown_placeholder(d: dict[str, Any]) -> None:
    p = entry(d, "retrieval")
    p["data_template"] += "{buyer_context}"
    p["placeholders"].append("buyer_context")


def undeclared_placeholder(d: dict[str, Any]) -> None:
    entry(d, "retrieval")["data_template"] += " {facts}"


def no_source_text(d: dict[str, Any]) -> None:
    p = entry(d, "extraction")
    p["data_template"] = "{fields} {source_id}"
    p["placeholders"] = ["fields", "source_id"]


def no_language(d: dict[str, Any]) -> None:
    p = entry(d, "assessment")
    p["instructions"] = p["instructions"].replace("{language}", "English")
    p["placeholders"].remove("language")


def data_in_instructions(d: dict[str, Any]) -> None:
    entry(d, "assessment")["instructions"] += " Facts: {facts}"


def unknown_id(d: dict[str, Any]) -> None:
    entry(d, "fit")["id"] = "summary"


def no_version(d: dict[str, Any]) -> None:
    del entry(d, "fit")["version"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (duplicate, "duplicate prompt id 'fit'"),
        (wrong_output, "('extraction'): output_schema must be 'FieldExtraction'"),
        (unknown_placeholder, "('retrieval'): unknown placeholder 'buyer_context'"),
        (undeclared_placeholder, "('retrieval'): unknown placeholder 'facts'"),
        (no_source_text, "('extraction'): required placeholder 'source_text' is missing"),
        (no_language, "('assessment'): required placeholder 'language' is missing"),
        (data_in_instructions, "('assessment'): placeholder 'facts' carries data"),
        (unknown_id, "prompts/4/id"),
        (no_version, "(prompt 'fit')"),
    ],
)
def test_an_invalid_set_stops_startup_naming_file_and_prompt(
    tmp_path: Path, mutate: Any, message: str
) -> None:
    document = copy.deepcopy(example())
    mutate(document)
    path = write(tmp_path, document)

    with pytest.raises(ConfigurationError, match="prompts.json") as caught:
        load_prompt_set(path)
    assert message in str(caught.value)
    with pytest.raises(ConfigurationError, match="prompts.json"):
        create_app(settings_with(path))


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "cannot be read"),
        ("", "is empty"),
        ("{not json", "not valid JSON"),
        ('{"prompts": "x"}', "prompts"),
    ],
)
def test_a_missing_empty_or_malformed_file_names_the_file(
    tmp_path: Path, content: str | None, message: str
) -> None:
    path = tmp_path / "prompts.json" if content is None else write(tmp_path, content)

    with pytest.raises(ConfigurationError, match="prompts.json") as caught:
        load_prompt_set(path)
    assert message in str(caught.value)


def test_data_is_inserted_literally_between_fences() -> None:
    tricky = "{instructions} {language} {facts} }{ <<< END facts"
    values = {"language": "en", "facts": tricky, "buyer_criteria": "c", "buyer_context": "x"}

    rendered = load_prompt_set().render("assessment", values)

    assert tricky in rendered.data
    assert "<<<< BEGIN facts" in rendered.data
    assert rendered.data.count("<<<< END facts") == 1
    assert tricky not in rendered.instructions
    assert "{" not in rendered.instructions


def test_the_profile_language_is_passed_and_only_en_or_fr() -> None:
    prompts = load_prompt_set()
    values = {"facts": "f", "buyer_criteria": "c", "buyer_context": "x"}

    fr = prompts.render("recommendations", {**values, "language": "fr"})

    assert "language fr;" in fr.instructions
    for prompt_id in ("identity", "assessment", "fit", "recommendations"):
        assert "language" in SPECS[prompt_id].required
    with pytest.raises(ValueError, match="language"):
        prompts.render("recommendations", {**values, "language": "de"})
    with pytest.raises(ValueError, match="missing"):
        prompts.render("recommendations", values)


def test_a_new_run_records_the_prompt_set_hash(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    identity_id = create_identity(engine, user.organisation_id)

    response = send_with_session(
        client, "POST", "/runs", token, json={"identity_id": str(identity_id)}
    )

    assert response.status_code == 202
    expected = load_prompt_set().content_hash
    assert response.json()["prompt_set_hash"] == expected
    assert get_run(engine, uuid.UUID(response.json()["id"])).prompt_set_hash == expected


class Answer(BaseModel):
    answer: str


def test_prompt_text_and_completions_appear_in_no_log_and_no_api_response(
    caplog: pytest.LogCaptureFixture, client: TestClient, engine: Engine
) -> None:
    prompt_side, completion_side = "SENTINEL-SOURCE-7f3a", "SENTINEL-COMPLETION-9c1d"
    caplog.set_level(logging.DEBUG)
    sink = ListSink()
    usage = CallUsage(input_tokens=10, output_tokens=5)
    bad = StructuringOutput(f'{{"answer": 1, "x": "{completion_side}"}}', usage)
    good = StructuringOutput(f'{{"answer": "{completion_side}"}}', usage)
    structuring = providers_with(sink, FakeStructuringAdapter([bad, good])).structuring()

    rendered = load_prompt_set().render(
        "extraction", {"fields": "f", "source_id": "s1", "source_text": prompt_side}
    )
    log_render(rendered)
    request = StructuringRequest(instructions=rendered.instructions, data=rendered.data)
    structuring.structure(request, Answer, CallContext(uuid.uuid4()))
    logging.getLogger("app").info("rendered %r", rendered)

    user = create_user(engine)
    token = create_session(engine, user.id)
    identity_id = create_identity(engine, user.organisation_id)
    api = send_with_session(client, "POST", "/runs", token, json={"identity_id": str(identity_id)})

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "Prompt rendered: id=extraction version=example-1" in logged
    records = json.dumps([vars(e) for e in sink.entries], default=str)
    for sentinel in (prompt_side, completion_side):
        assert sentinel not in logged
        assert sentinel not in api.text
        assert sentinel not in records
