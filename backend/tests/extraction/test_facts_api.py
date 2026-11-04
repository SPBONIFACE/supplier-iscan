"""GET /runs/{id}/facts and the extraction counts on GET /runs/{id} (#23): the contract, one entry
per fact field, never a negative statement, the certification link, organisation isolation."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.extraction.settings import DEFAULT_CERTSEARCH_URL
from tests.auth_support import send_with_session
from tests.contract.test_auth_contract import assert_matches_contract
from tests.extraction.support import (
    FACT_FIELDS,
    Asked,
    add_source,
    extract_with,
    item,
    scripted,
    set_identity,
)
from tests.factories import create_organisation, create_session, create_user
from tests.isolation_support import OwnedResource, OwnerOrganisation, assert_organisation_isolation
from tests.runs_support import create_run

PAGE = "Acme Supplies SA was founded in 2005 in Lyon. We hold ISO 14001 certification."


def answer(asked: Asked) -> list[dict[str, Any]]:
    out = []
    if "founding_year" in asked.fields:
        out.append(item("founding_year", "2005", "was founded in 2005 in Lyon", asked.source_id))
    if "environmental_management" in asked.fields:
        out.append(
            item("environmental_management", "ISO 14001", "We hold ISO 14001", asked.source_id)
        )
    if "legal_form" in asked.fields:  # discarded: the quote is not in the page
        out.append(item("legal_form", "SA", "a public limited company", asked.source_id))
    return out


def extracted_run(engine: Engine, organisation_id: uuid.UUID, text: str = PAGE) -> uuid.UUID:
    run_id = create_run(engine, organisation_id, stage="extraction", enqueue=False)
    set_identity(engine, run_id, website="https://www.acme.example")
    add_source(engine, organisation_id, run_id, "https://www.acme.example/about", text)
    extract_with(engine, organisation_id, run_id, scripted(answer))
    return run_id


def get(client: TestClient, token: str, path: str) -> Any:
    return send_with_session(client, "GET", path, token)


def test_the_facts_endpoint_returns_one_entry_per_fact_field(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = extracted_run(engine, user.organisation_id)

    response = get(client, token, f"/runs/{run_id}/facts")

    assert response.status_code == 200
    assert_matches_contract(response, "/runs/{id}/facts", "get")
    items = response.json()["items"]
    assert [entry["field"] for entry in items] == FACT_FIELDS  # definition order, facts only
    by_field = {entry["field"]: entry for entry in items}
    year = by_field["founding_year"]
    assert year["status"] == "proposed" and year["value"] == "2005"
    assert year["quote"] == "was founded in 2005 in Lyon" and year["quote_redacted"] is False
    assert year["source_url"] == "https://www.acme.example/about"
    assert year["source_type"] == "supplier_claim"
    assert year["publisher"] == "acme.example" and year["author"] is None
    assert year["fetched_at"] is not None and year["verification_url"] is None
    assert year["section"] == "company_overview"


def test_a_field_without_a_kept_value_is_not_found_and_says_nothing_about_the_supplier(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = extracted_run(engine, user.organisation_id)

    response = get(client, token, f"/runs/{run_id}/facts")

    gap = {e["field"]: e for e in response.json()["items"]}["legal_form"]  # its value was discarded
    assert gap["status"] == "not_found"
    for member in (
        "value",
        "quote",
        "source_id",
        "source_url",
        "source_type",
        "publisher",
        "author",
        "fetched_at",
        "verification_url",
    ):
        assert gap[member] is None, member
    assert gap["quote_redacted"] is False
    assert "not certified" not in response.text.lower()


def test_a_kept_certification_carries_the_verification_link_and_a_gap_does_not(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = extracted_run(engine, user.organisation_id)

    by_field = {e["field"]: e for e in get(client, token, f"/runs/{run_id}/facts").json()["items"]}

    assert by_field["environmental_management"]["verification_url"] == DEFAULT_CERTSEARCH_URL
    assert by_field["quality_management"]["status"] == "not_found"
    assert by_field["quality_management"]["verification_url"] is None
    assert by_field["quality_management"]["value"] is None  # never "not certified"


def test_the_verification_link_is_a_setting(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IAF_CERTSEARCH_URL", "https://certsearch.example/verify")
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = extracted_run(engine, user.organisation_id)

    by_field = {e["field"]: e for e in get(client, token, f"/runs/{run_id}/facts").json()["items"]}

    assert (
        by_field["environmental_management"]["verification_url"]
        == "https://certsearch.example/verify"
    )


def test_a_run_without_extraction_has_no_facts(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = create_run(engine, user.organisation_id)

    response = get(client, token, f"/runs/{run_id}/facts")

    assert response.status_code == 200 and response.json() == {"items": []}
    assert_matches_contract(response, "/runs/{id}/facts", "get")


def test_the_run_shows_the_grounding_failures_and_invalid_items(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = extracted_run(engine, user.organisation_id)  # one value was discarded

    response = get(client, token, f"/runs/{run_id}")

    assert response.status_code == 200
    assert_matches_contract(response, "/runs/{id}", "get")
    assert (response.json()["grounding_failures"], response.json()["invalid_items"]) == (1, 0)
    fresh = get(client, token, f"/runs/{create_run(engine, user.organisation_id)}").json()
    assert (fresh["grounding_failures"], fresh["invalid_items"]) == (0, 0)


def test_an_unknown_run_answers_404_like_any_other(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)

    response = get(client, token, f"/runs/{uuid.uuid4()}/facts")

    assert response.status_code == 404
    assert_matches_contract(response, "/runs/{id}/facts", "get")


def make_facts_resource(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
    run_id = extracted_run(
        engine, owner.id, "Distinctive Quote Text. Acme was founded in 2005 in Lyon."
    )
    return OwnedResource(
        path=f"/runs/{run_id}/facts",
        missing_path=f"/runs/{uuid.uuid4()}/facts",
        marker="was founded in 2005 in Lyon",
    )


def test_the_facts_endpoint_is_isolated_between_organisations(
    client: TestClient, engine: Engine
) -> None:
    assert_organisation_isolation(client, engine, "GET", make_facts_resource)


def test_facts_of_another_organisation_are_not_listed(client: TestClient, engine: Engine) -> None:
    mine = create_user(engine)
    token = create_session(engine, mine.id)
    theirs = extracted_run(engine, create_organisation(engine, name="Other"))

    assert get(client, token, f"/runs/{theirs}/facts").status_code == 404
