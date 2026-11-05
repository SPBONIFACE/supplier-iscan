"""GET /comparison (#38): the contract, the limits, the all-or-nothing 404, isolation, and the
neutral shape (owner decision D-073: facts only, nothing that ranks or scores a supplier)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Fact, ProfileRun
from tests.auth_support import send_with_session
from tests.contract.test_auth_contract import assert_matches_contract
from tests.factories import create_organisation, create_session, create_user
from tests.isolation_support import OwnedResource, OwnerOrganisation, assert_organisation_isolation
from tests.runs_support import create_identity, create_run
from tests.support import LOCAL_ORIGIN, make_client

FETCHED = datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
NOT_ASSESSED = "Not assessed"


def add_fact(
    engine: Engine,
    organisation_id: uuid.UUID,
    run_id: uuid.UUID,
    field: str,
    value: str | None,
    *,
    section: str = "company_overview",
    status: str = "proposed",
) -> None:
    with Session(engine) as db:
        found = status != "not_found"
        db.add(
            Fact(
                organisation_id=organisation_id,
                run_id=run_id,
                section=section,
                field=field,
                status=status,
                value=value if found else None,
                quote=f"quote for {value}" if found else None,
                source_url="https://www.acme.example/about" if found else None,
                source_type="supplier_claim" if found else None,
                publisher="acme.example" if found else None,
                fetched_at=FETCHED if found else None,
            )
        )
        db.commit()


def finished_run(
    engine: Engine, organisation_id: uuid.UUID, name: str, status: str = "completed"
) -> uuid.UUID:
    run_id = create_run(engine, organisation_id, legal_name=name, status=status, enqueue=False)
    add_fact(engine, organisation_id, run_id, "founding_year", "2005")
    add_fact(engine, organisation_id, run_id, "legal_form", None, status="not_found")
    return run_id


def compare(client: TestClient, token: str, *run_ids: object) -> Any:
    query = "&".join(f"run_ids={run_id}" for run_id in run_ids)
    return send_with_session(client, "GET", f"/comparison?{query}", token)


def test_the_comparison_lists_the_facts_of_each_run_in_request_order(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    first = finished_run(engine, user.organisation_id, "First Supplier SA")
    second = finished_run(engine, user.organisation_id, "Second Supplier GmbH")

    response = compare(client, token, second, first)

    assert response.status_code == 200
    assert_matches_contract(response, "/comparison", "get")
    items = response.json()["items"]
    assert [entry["run"]["id"] for entry in items] == [str(second), str(first)]
    assert items[0]["run"]["supplier_name"] == "Second Supplier GmbH"
    by_field = {fact["field"]: fact for fact in items[1]["facts"]}
    assert by_field["founding_year"]["value"] == "2005"
    assert by_field["founding_year"]["quote"] == "quote for 2005"
    assert by_field["founding_year"]["source_type"] == "supplier_claim"
    assert by_field["legal_form"]["status"] == "not_found"
    assert by_field["legal_form"]["value"] is None and by_field["legal_form"]["quote"] is None


def test_duplicate_ids_count_once_and_one_distinct_id_is_not_enough(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    first = finished_run(engine, user.organisation_id, "First Supplier SA")
    second = finished_run(engine, user.organisation_id, "Second Supplier GmbH")

    twice = compare(client, token, first, str(first).upper())
    assert twice.status_code == 422
    assert_matches_contract(twice, "/comparison", "get")
    assert compare(client, token, first).status_code == 422
    assert compare(client, token).status_code == 422

    again = compare(client, token, first, second, first)
    assert again.status_code == 200
    assert len(again.json()["items"]) == 2


def test_more_than_the_configured_maximum_answers_422(
    engine: Engine, settings: Settings, database_url: str
) -> None:
    limited = make_client(
        settings=Settings(
            database_url=database_url,
            allowed_origins=(LOCAL_ORIGIN,),
            comparison_max_profiles=3,
            run_budget_eur=settings.run_budget_eur,
        ),
        engine=engine,
    )
    user = create_user(engine)
    token = create_session(engine, user.id)
    runs = [finished_run(engine, user.organisation_id, f"Supplier {i}") for i in range(4)]

    assert compare(limited, token, *runs[:3]).status_code == 200
    over = compare(limited, token, *runs)
    assert over.status_code == 422
    assert_matches_contract(over, "/comparison", "get")
    assert "3" in over.json()["errors"][0]["message"]


def test_one_foreign_or_unknown_id_makes_the_whole_request_404_without_partial_data(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    own = finished_run(engine, user.organisation_id, "Own Supplier SA")
    other = create_organisation(engine)
    foreign = finished_run(engine, other, "Foreign Distinctive SA")
    unknown = uuid.uuid4()

    foreign_answer = compare(client, token, own, foreign)
    unknown_answer = compare(client, token, own, unknown)
    malformed_answer = compare(client, token, own, "not-an-id")

    assert foreign_answer.status_code == 404
    assert_matches_contract(foreign_answer, "/comparison", "get")
    assert foreign_answer.json() == unknown_answer.json() == malformed_answer.json()
    assert unknown_answer.status_code == malformed_answer.status_code == 404
    assert "Foreign Distinctive" not in foreign_answer.text
    assert "Own Supplier" not in foreign_answer.text  # no partial data


def make_comparison(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
    first = finished_run(engine, owner.id, "Distinctive Comparison SA")
    second = finished_run(engine, owner.id, "Second Distinctive GmbH")
    return OwnedResource(
        path=f"/comparison?run_ids={first}&run_ids={second}",
        missing_path=f"/comparison?run_ids={first}&run_ids={uuid.uuid4()}",
        marker="Distinctive Comparison SA",
    )


def test_the_comparison_is_isolated_between_organisations_and_for_the_administrator(
    client: TestClient, engine: Engine
) -> None:
    assert_organisation_isolation(client, engine, "GET", make_comparison)


def test_a_run_in_progress_has_no_facts_and_a_partial_run_keeps_its_flags(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    running = create_run(engine, user.organisation_id, status="running", enqueue=False)
    add_fact(engine, user.organisation_id, running, "founding_year", "1999")
    partial = finished_run(engine, user.organisation_id, "Partial Supplier SA", status="partial")
    with Session(engine) as db:
        db.execute(
            update(ProfileRun)
            .where(ProfileRun.id == partial)
            .values(uncovered_sections=["certifications"], identity_to_verify=True)
        )
        db.commit()

    response = compare(client, token, running, partial)

    assert response.status_code == 200
    first, second = response.json()["items"]
    assert first["run"]["status"] == "running" and first["facts"] == []
    assert second["run"]["status"] == "partial"
    assert second["run"]["uncovered_sections"] == ["certifications"]
    assert second["run"]["identity_to_verify"] is True
    # A field of an uncovered section is absent, never a "not_found" entry.
    assert {fact["section"] for fact in second["facts"]} == {"company_overview"}


def test_a_natural_person_supplier_carries_no_assessment_gap_score_or_ranking(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    person_identity = create_identity(
        engine, user.organisation_id, legal_name="Solo Founder", natural_person=True
    )
    person = finished_run(engine, user.organisation_id, "Company SA")
    with Session(engine) as db:
        db.execute(
            update(ProfileRun).where(ProfileRun.id == person).values(identity_id=person_identity)
        )
        db.commit()
    other = finished_run(engine, user.organisation_id, "Other Company SA")

    response = compare(client, token, person, other)

    assert response.status_code == 200
    text = response.text.lower()
    for word in ("not assessed", "score", "rank", "assessment", "evidence_gap", "weakness"):
        assert word not in text, word
    assert response.json()["items"][0]["run"]["natural_person"] is True


def test_the_comparison_requires_a_session(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    run = finished_run(engine, user.organisation_id, "Own Supplier SA")

    response = client.get(f"/comparison?run_ids={run}&run_ids={run}")

    assert response.status_code == 401
    assert_matches_contract(response, "/comparison", "get")


def test_the_organisation_states_the_maximum_for_the_screens(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)

    response = send_with_session(client, "GET", "/organisation", token)

    assert response.json()["comparison_max_profiles"] == 10
    assert_matches_contract(response, "/organisation", "get")
