"""The member's inputs for a run (#26): fit criteria, buyer context and buyer fields. Storage,
who and when, the version check (409 with the current value), limits, field kinds, isolation and
the contract."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import BuyerInput
from tests.auth_support import assert_requires_session, send_with_session
from tests.contract.test_auth_contract import assert_matches_contract
from tests.factories import create_organisation, create_session, create_user
from tests.isolation_support import OwnedResource, OwnerOrganisation, assert_organisation_isolation
from tests.runs_support import create_run
from tests.support import LOCAL_ORIGIN, make_client

CONTEXT: dict[str, Any] = {
    "relationship": "incumbent",
    "current_share_pct": 30,
    "contract_end_date": "2027-06-30",
    "strategic_intent": ["dual_sourcing", "risk_reduction"],
    "notes": "Renewal talks in spring.",
    "version": 0,
}


def put(client: TestClient, token: str, run_id: uuid.UUID, tail: str, body: dict[str, Any]) -> Any:
    return send_with_session(client, "PUT", f"/runs/{run_id}/{tail}", token, json=body)


def setup(engine: Engine) -> tuple[str, uuid.UUID, uuid.UUID]:
    user = create_user(engine)
    token = create_session(engine, user.id)
    return token, create_run(engine, user.organisation_id, enqueue=False), user.id


def stored(engine: Engine, run_id: uuid.UUID, field: str) -> BuyerInput | None:
    with Session(engine) as db:
        return db.scalar(
            select(BuyerInput).where(BuyerInput.run_id == run_id, BuyerInput.field == field)
        )


# --- criteria --------------------------------------------------------------------------------


def test_criteria_are_stored_with_who_and_when_and_replaced_by_the_next_put(
    client: TestClient, engine: Engine
) -> None:
    token, run_id, user_id = setup(engine)

    first = put(
        client, token, run_id, "criteria", {"criteria": ["ISO 14001", " Dual site "], "version": 0}
    )

    assert first.status_code == 200
    assert_matches_contract(first, "/runs/{id}/criteria", "put")
    body = first.json()
    assert body["criteria"] == ["ISO 14001", "Dual site"] and body["version"] == 1
    assert body["updated_by"] == str(user_id) and body["updated_at"]
    row = stored(engine, run_id, "fit_criteria")
    assert row is not None and row.updated_by == user_id

    second = put(client, token, run_id, "criteria", {"criteria": ["Only one"], "version": 1})
    assert second.json()["criteria"] == ["Only one"] and second.json()["version"] == 2


def test_an_empty_list_is_accepted_and_means_no_criteria(
    client: TestClient, engine: Engine
) -> None:
    token, run_id, _ = setup(engine)

    response = put(client, token, run_id, "criteria", {"criteria": [], "version": 0})

    assert response.status_code == 200 and response.json()["criteria"] == []


def test_criteria_that_are_too_long_or_empty_are_refused_with_422(engine: Engine) -> None:
    token, run_id, _ = setup(engine)
    settings = Settings(database_url=None, allowed_origins=(LOCAL_ORIGIN,), criteria_max_chars=20)

    client = make_client(settings=settings, engine=engine)

    long = put(client, token, run_id, "criteria", {"criteria": ["a" * 11, "b" * 10], "version": 0})
    fits = put(client, token, run_id, "criteria", {"criteria": ["a" * 10, "b" * 10], "version": 0})
    blank = put(client, token, run_id, "criteria", {"criteria": ["  "], "version": 1})
    missing = put(client, token, run_id, "criteria", {"criteria": ["x"]})

    assert long.status_code == 422 and fits.status_code == 200
    assert blank.status_code == 422 and missing.status_code == 422
    assert "a" * 11 not in long.text  # the submitted value is never echoed
    assert_matches_contract(long, "/runs/{id}/criteria", "put")


def test_two_members_editing_the_criteria_at_once_cannot_lose_an_edit(
    client: TestClient, engine: Engine
) -> None:
    first = create_user(engine)
    second = create_user(engine, organisation_id=first.organisation_id)
    run_id = create_run(engine, first.organisation_id, enqueue=False)
    token_a, token_b = create_session(engine, first.id), create_session(engine, second.id)

    saved = put(client, token_a, run_id, "criteria", {"criteria": ["First"], "version": 0})
    stale = put(client, token_b, run_id, "criteria", {"criteria": ["Lost edit"], "version": 0})
    ahead = put(client, token_b, run_id, "criteria", {"criteria": ["Ahead"], "version": 5})
    retry = put(client, token_b, run_id, "criteria", {"criteria": ["Merged"], "version": 1})

    assert saved.status_code == 200 and stale.status_code == 409 and ahead.status_code == 409
    assert_matches_contract(stale, "/runs/{id}/criteria", "put")
    assert (
        stale.json()["current"]["criteria"] == ["First"] and stale.json()["current"]["version"] == 1
    )
    assert retry.status_code == 200 and retry.json()["updated_by"] == str(second.id)
    row = stored(engine, run_id, "fit_criteria")
    assert row is not None and row.version == 2 and "Lost edit" not in row.text


def test_a_write_with_a_version_when_nothing_is_stored_answers_409_with_no_current(
    client: TestClient, engine: Engine
) -> None:
    token, run_id, _ = setup(engine)

    response = put(client, token, run_id, "criteria", {"criteria": ["x"], "version": 3})

    assert response.status_code == 409 and response.json()["current"] is None
    assert_matches_contract(response, "/runs/{id}/criteria", "put")


# --- buyer context ---------------------------------------------------------------------------


def test_the_buyer_context_is_stored_as_a_structured_value_with_a_version(
    client: TestClient, engine: Engine
) -> None:
    token, run_id, user_id = setup(engine)

    response = put(client, token, run_id, "buyer-context", CONTEXT)

    assert response.status_code == 200
    assert_matches_contract(response, "/runs/{id}/buyer-context", "put")
    body = response.json()
    assert body["relationship"] == "incumbent" and body["current_share_pct"] == 30
    assert body["contract_end_date"] == "2027-06-30" and body["version"] == 1
    assert body["strategic_intent"] == ["dual_sourcing", "risk_reduction"]
    assert body["notes"] == "Renewal talks in spring." and body["updated_by"] == str(user_id)

    minimal = put(client, token, run_id, "buyer-context", {"relationship": "new", "version": 1})
    assert minimal.status_code == 200 and minimal.json()["version"] == 2
    assert minimal.json()["current_share_pct"] is None and minimal.json()["strategic_intent"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"current_share_pct": 100.5},
        {"current_share_pct": -1},
        {"contract_end_date": "2027-02-30"},
        {"contract_end_date": "next spring"},
        {"strategic_intent": ["world_domination"]},
        {"strategic_intent": ["dual_sourcing", "dual_sourcing"]},
        {"relationship": "friend"},
        {"relationship": None},
        {"notes": "n" * 11},
        {"unknown_part": 1},
    ],
)
def test_an_invalid_buyer_context_answers_422(engine: Engine, change: dict[str, Any]) -> None:
    token, run_id, _ = setup(engine)
    settings = Settings(
        database_url=None, allowed_origins=(LOCAL_ORIGIN,), buyer_notes_max_chars=10
    )
    client = make_client(settings=settings, engine=engine)

    response = put(client, token, run_id, "buyer-context", {**CONTEXT, **change})

    assert response.status_code == 422, response.text
    assert_matches_contract(response, "/runs/{id}/buyer-context", "put")
    assert stored(engine, run_id, "buyer_context") is None


def test_an_outdated_buyer_context_version_answers_409_with_the_current_value(
    client: TestClient, engine: Engine
) -> None:
    token, run_id, _ = setup(engine)
    assert put(client, token, run_id, "buyer-context", CONTEXT).status_code == 200

    stale = put(client, token, run_id, "buyer-context", {**CONTEXT, "relationship": "new"})

    assert stale.status_code == 409
    assert_matches_contract(stale, "/runs/{id}/buyer-context", "put")
    assert stale.json()["current"]["relationship"] == "incumbent"
    assert stale.json()["current"]["version"] == 1


# --- buyer fields (free text) ----------------------------------------------------------------


def test_a_buyer_field_stores_free_text_with_updated_by_and_updated_at(
    client: TestClient, engine: Engine
) -> None:
    token, run_id, user_id = setup(engine)

    first = put(
        client, token, run_id, "buyer-inputs/buyer_notes", {"text": "Call Pat.", "version": 0}
    )
    second = put(client, token, run_id, "buyer-inputs/buyer_notes", {"text": "", "version": 1})

    assert first.status_code == 200 and second.status_code == 200
    assert_matches_contract(first, "/runs/{id}/buyer-inputs/{field}", "put")
    body = first.json()
    assert body["field"] == "buyer_notes" and body["text"] == "Call Pat." and body["version"] == 1
    assert body["updated_by"] == str(user_id) and body["updated_at"]
    assert second.json()["text"] == "" and second.json()["version"] == 2
    stale = put(client, token, run_id, "buyer-inputs/buyer_notes", {"text": "lost", "version": 1})
    assert stale.status_code == 409 and stale.json()["current"]["text"] == ""
    assert_matches_contract(stale, "/runs/{id}/buyer-inputs/{field}", "put")


@pytest.mark.parametrize(
    "field",
    ["fit_criteria", "buyer_context", "strengths", "founding_year", "no_such_field"],
)
def test_a_field_that_is_not_of_kind_buyer_answers_422(
    client: TestClient, engine: Engine, field: str
) -> None:
    token, run_id, _ = setup(engine)

    response = put(client, token, run_id, f"buyer-inputs/{field}", {"text": "x", "version": 0})

    assert response.status_code == 422
    assert_matches_contract(response, "/runs/{id}/buyer-inputs/{field}", "put")
    assert stored(engine, run_id, field) is None


def test_buyer_text_that_is_too_long_answers_422(engine: Engine) -> None:
    token, run_id, _ = setup(engine)
    settings = Settings(database_url=None, allowed_origins=(LOCAL_ORIGIN,), buyer_text_max_chars=15)
    client = make_client(settings=settings, engine=engine)

    long = put(client, token, run_id, "buyer-inputs/buyer_notes", {"text": "x" * 16, "version": 0})
    fits = put(client, token, run_id, "buyer-inputs/buyer_notes", {"text": "x" * 15, "version": 0})

    assert long.status_code == 422 and fits.status_code == 200


# --- session and isolation -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tail", "body"),
    [
        ("criteria", {"criteria": ["Distinctive criterion"], "version": 0}),
        ("buyer-context", {"relationship": "new", "notes": "Distinctive note", "version": 0}),
        ("buyer-inputs/buyer_notes", {"text": "Distinctive text", "version": 0}),
    ],
)
def test_the_writes_need_a_session_and_are_isolated_between_organisations(
    client: TestClient, engine: Engine, tail: str, body: dict[str, Any]
) -> None:
    def make(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
        run_id = create_run(engine, owner.id, enqueue=False)
        return OwnedResource(
            path=f"/runs/{run_id}/{tail}",
            missing_path=f"/runs/{uuid.uuid4()}/{tail}",
            marker="Distinctive",
        )

    assert_requires_session(client, engine, "PUT", f"/runs/{uuid.uuid4()}/{tail}", json=body)
    assert_organisation_isolation(client, engine, "PUT", make, json=body)


def test_another_organisations_write_changes_nothing(client: TestClient, engine: Engine) -> None:
    token, run_id, _ = setup(engine)
    intruder = create_user(engine, organisation_id=create_organisation(engine))
    foreign = create_session(engine, intruder.id)

    response = put(client, foreign, run_id, "criteria", {"criteria": ["Hijack"], "version": 0})

    assert response.status_code == 404 and stored(engine, run_id, "fit_criteria") is None
    assert token  # the owner is untouched
