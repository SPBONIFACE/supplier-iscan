"""A run that reaches its cost budget (#30): it ends `partial` with the sections it did not cover
and a plain explanation, in collection, extraction and assessment; what was produced stays
readable; a skipped section is never "No public evidence found"; and the budget's interplay with
pauses (outage, redaction failure), `insufficient_sources`, the quota and later drafting."""

import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import Database
from app.models import AssessmentItem, Fact, Job, Organisation, ProfileRun
from app.providers import Providers
from app.providers.errors import ProviderCallError
from app.providers.fake import FakeRetrievalAdapter
from app.redaction import RedactionGate, RedactionUnavailable
from app.runs.executor import RunEnvironment, execute_run
from app.runs.refusal import profiles_remaining
from app.runs.stages import Stage, no_op
from tests.assessment.test_stage import add_fact, answer, items_of, priority, strength
from tests.auth_support import send_with_session
from tests.collection.test_adaptive_stage import failures_of, make_stage, sources_of, start
from tests.contract.test_auth_contract import assert_matches_contract
from tests.extraction.support import (
    DEFINITION,
    FACT_FIELDS,
    PROMPTS,
    Asked,
    add_source,
    facts_of,
    item,
    set_identity,
)
from tests.extraction.support import stage as extraction_stage
from tests.factories import create_organisation, create_session, create_user
from tests.limits.support import CALL_COST, Billed, BilledText, allow, providers_for, total_cost
from tests.runs_support import add_usage, create_run, get_run
from tests.support import LOCAL_ORIGIN, make_client

PAGE = "Acme Supplies SA was founded in 2005 in Lyon. We hold ISO 14001 certification."
SECTIONS = [section.id for section in DEFINITION.sections]
FACT_SECTIONS = [
    s.id for s in DEFINITION.sections if any(f.kind == "fact" for f in s.fields)
]  # company_overview, production_footprint, certifications
ASSESSMENT_SECTIONS = [
    s.id for s in DEFINITION.sections if any(f.kind == "assessment" for f in s.fields)
]  # swot
NO_EVIDENCE = '"No public evidence found"'


def pipeline(
    extraction: Stage = no_op, assessment: Stage = no_op, collection: Stage = no_op
) -> Any:
    return {
        "identity": no_op,
        "collection": collection,
        "extraction": extraction,
        "assessment": assessment,
    }


def environment(engine: Engine, stages: Any, providers: Providers | None) -> RunEnvironment:
    return RunEnvironment(Database(None, engine), stages, providers, lambda: None, DEFINITION)


def respond(asked: Asked) -> list[dict[str, Any]]:
    found = []
    if "founding_year" in asked.fields:
        found.append(item("founding_year", "2005", "was founded in 2005 in Lyon", asked.source_id))
    if "environmental_management" in asked.fields:
        found.append(
            item("environmental_management", "ISO 14001", "We hold ISO 14001", asked.source_id)
        )
    return found


def extraction_run(engine: Engine, text: str = PAGE) -> tuple[uuid.UUID, uuid.UUID]:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, stage="extraction", enqueue=False)
    set_identity(engine, run_id, website="https://www.acme.example")
    add_source(engine, organisation_id, run_id, "https://www.acme.example/about", text)
    return organisation_id, run_id


def member(client: TestClient, engine: Engine, organisation_id: uuid.UUID) -> str:
    return create_session(engine, create_user(engine, organisation_id=organisation_id).id)


def read(client: TestClient, token: str, path: str) -> Any:
    response = send_with_session(client, "GET", path, token)
    assert response.status_code == 200, response.text
    return response


def complete_facts(engine: Engine, organisation_id: uuid.UUID, run_id: uuid.UUID) -> None:
    """A fact row for every fact field (the extraction stage's result), `not_found` when absent."""
    with Session(engine) as db:
        have = set(db.scalars(select(Fact.field).where(Fact.run_id == run_id)))
    for field in FACT_FIELDS:
        if field not in have:
            add_fact(engine, organisation_id, run_id, field, None)


# --- collection -------------------------------------------------------------------------------


def test_a_budget_reached_during_collection_ends_the_run_partial_with_every_section_uncovered(
    client: TestClient, engine: Engine
) -> None:
    organisation_id, run_id = start(engine, website=None)
    adapter = FakeRetrievalAdapter([[]])
    providers = providers_for(engine, retrieval=adapter, budget=Decimal("0.05"))

    execute_run(environment(engine, pipeline(collection=make_stage({})), providers), run_id)

    run = get_run(engine, run_id)
    assert run.status == "partial" and run.finished_at is not None
    assert adapter.calls == []  # the call was not made
    assert run.uncovered_sections == [*SECTIONS, "recommendations"]
    assert run.counts_against_quota is True
    assert run.partial_explanation is not None
    assert "cost budget" in run.partial_explanation
    assert "search for further sources was not made" in run.partial_explanation
    assert f"it is not {NO_EVIDENCE}" in run.partial_explanation
    (failure,) = failures_of(engine, run_id)
    assert (failure.strategy, failure.kind) == ("retrieval", "attempt_cap")
    assert "cost budget" in failure.message
    # Not "insufficient sources": nothing is known about what exists, the search was not made.
    assert run.status != "insufficient_sources" and run.error is None
    token = member(client, engine, organisation_id)
    body = read(client, token, f"/runs/{run_id}").json()
    assert_matches_contract(read(client, token, f"/runs/{run_id}"), "/runs/{id}", "get")
    assert body["status"] == "partial" and body["uncovered_sections"] == run.uncovered_sections
    assert body["partial_explanation"] == run.partial_explanation


def test_the_sources_collected_before_the_budget_was_reached_are_kept_and_readable(
    client: TestClient, engine: Engine
) -> None:
    from tests.collection.support import HOST, html

    organisation_id, run_id = start(engine)
    stage = make_stage({(HOST, "/"): html("<h1>Acme Supplies SA</h1><p>Bolts since 1950.</p>")})
    providers = providers_for(engine, retrieval=FakeRetrievalAdapter([[]]), budget=Decimal("0.05"))

    execute_run(environment(engine, pipeline(collection=stage), providers), run_id)

    assert get_run(engine, run_id).status == "partial"
    assert {s.url for s in sources_of(engine)} == {f"https://{HOST}/"}
    token = member(client, engine, organisation_id)
    listed = read(client, token, f"/runs/{run_id}/sources").json()["items"]
    assert [entry["url"] for entry in listed] == [f"https://{HOST}/"]
    assert get_run(engine, run_id).identity_to_verify is False  # the stage finished its notes
    assert read(client, token, f"/runs/{run_id}/facts").json()["items"] == []


def test_without_a_budget_problem_a_run_with_no_source_is_still_insufficient_sources(
    engine: Engine,
) -> None:
    _organisation_id, run_id = start(engine, website=None)
    adapter = FakeRetrievalAdapter([[] for _ in range(4)])  # one per focus
    providers = providers_for(engine, retrieval=adapter, budget=Decimal("5"))

    execute_run(environment(engine, pipeline(collection=make_stage({})), providers), run_id)

    run = get_run(engine, run_id)
    assert run.status == "insufficient_sources" and run.counts_against_quota is False
    assert len(adapter.calls) == 4
    assert run.uncovered_sections == [] and run.partial_explanation is None


# --- extraction -------------------------------------------------------------------------------


def test_a_budget_reached_during_extraction_keeps_the_sections_done_and_lists_the_others(
    client: TestClient, engine: Engine
) -> None:
    organisation_id, run_id = extraction_run(engine)
    adapter = Billed(outputs=[], respond=respond)
    providers = providers_for(engine, structuring=adapter, budget=allow(1))

    execute_run(environment(engine, pipeline(extraction=extraction_stage()), providers), run_id)

    run = get_run(engine, run_id)
    assert run.status == "partial" and run.counts_against_quota is True
    assert len(adapter.asked) == 1 and total_cost(engine, run_id) == CALL_COST
    assert run.uncovered_sections == [*FACT_SECTIONS[1:], *ASSESSMENT_SECTIONS, "recommendations"]
    facts = facts_of(engine, run_id)
    first_section = [f.id for f in DEFINITION.sections[0].fields if f.kind == "fact"]
    assert set(facts) == set(first_section)  # the section that was examined, in full
    assert facts["founding_year"].status == "proposed"
    assert facts["legal_form"].status == "not_found"  # the text was read: that is the usual meaning
    # Nothing is stored, so nothing is shown, for the sections that were never read.
    token = member(client, engine, organisation_id)
    listed = read(client, token, f"/runs/{run_id}/facts").json()["items"]
    assert {entry["field"] for entry in listed} == set(first_section)
    assert_matches_contract(read(client, token, f"/runs/{run_id}/facts"), "/runs/{id}/facts", "get")
    assert read(client, token, f"/runs/{run_id}/sources").json()["items"]  # earlier stage, readable
    explanation = read(client, token, f"/runs/{run_id}").json()["partial_explanation"]
    assert "stopped while extracting facts" in explanation
    assert DEFINITION.sections[1].labels["en"] in explanation
    assert DEFINITION.sections[0].labels["en"] not in explanation.split("Not covered:")[1]


def test_a_section_cut_short_keeps_the_values_found_and_stores_no_gap_for_the_rest(
    engine: Engine,
) -> None:
    text = "Acme Supplies SA was founded in 2005 in Lyon. " + "padding " * 60
    _organisation_id, run_id = extraction_run(engine, text)
    adapter = Billed(outputs=[], respond=respond)
    providers = providers_for(engine, structuring=adapter, budget=allow(1))

    execute_run(
        environment(engine, pipeline(extraction=extraction_stage(max_input_chars=100)), providers),
        run_id,
    )

    run = get_run(engine, run_id)
    assert run.status == "partial" and len(adapter.asked) == 1
    facts = facts_of(engine, run_id)
    assert set(facts) == {"founding_year"}  # found, kept; the other fields were not examined
    assert facts["founding_year"].value == "2005"
    assert run.uncovered_sections[0] == FACT_SECTIONS[0]  # partly extracted: still uncovered
    assert "not_found" not in {fact.status for fact in facts.values()}


def test_a_budget_too_small_for_one_call_makes_no_call_and_keeps_the_sources(
    client: TestClient, engine: Engine
) -> None:
    organisation_id, run_id = extraction_run(engine)
    adapter = Billed(outputs=[], respond=respond)
    providers = providers_for(engine, structuring=adapter, budget=Decimal("0.001"))

    execute_run(environment(engine, pipeline(extraction=extraction_stage()), providers), run_id)

    run = get_run(engine, run_id)
    assert run.status == "partial" and adapter.asked == [] and facts_of(engine, run_id) == {}
    assert run.uncovered_sections == [*FACT_SECTIONS, *ASSESSMENT_SECTIONS, "recommendations"]
    token = member(client, engine, organisation_id)
    assert read(client, token, f"/runs/{run_id}/sources").json()["items"]
    assert read(client, token, f"/runs/{run_id}/facts").json() == {"items": []}


# --- assessment -------------------------------------------------------------------------------


def assessed_run(engine: Engine) -> tuple[uuid.UUID, uuid.UUID, dict[str, uuid.UUID]]:
    from tests.assessment.test_stage import setup

    organisation_id, run_id, facts = setup(engine)
    complete_facts(engine, organisation_id, run_id)
    return organisation_id, run_id, facts


def assessment_stage() -> Stage:
    from app.assessment.stage import make_assessment_stage

    return make_assessment_stage(DEFINITION, PROMPTS)


def test_a_budget_reached_during_assessment_keeps_the_statements_drafted_and_lists_the_rest(
    client: TestClient, engine: Engine
) -> None:
    organisation_id, run_id, facts = assessed_run(engine)
    quality = facts["quality_management"]
    adapter = BilledText([answer(strength(quality)), answer(priority(quality))])
    providers = providers_for(engine, structuring=adapter, budget=allow(1))

    execute_run(environment(engine, pipeline(assessment=assessment_stage()), providers), run_id)

    run = get_run(engine, run_id)
    assert run.status == "partial" and len(adapter.calls) == 1
    assert run.uncovered_sections == ["recommendations"]
    assert [i.kind for i in items_of(engine, run_id)] == ["strength"]
    token = member(client, engine, organisation_id)
    body = read(client, token, f"/runs/{run_id}/assessment").json()
    assert_matches_contract(
        read(client, token, f"/runs/{run_id}/assessment"), "/runs/{id}/assessment", "get"
    )
    assert body["status"] == "partial"  # it does not look complete
    assert [entry["kind"] for entry in body["items"]] == ["strength"]
    assert len(read(client, token, f"/runs/{run_id}/facts").json()["items"]) == len(FACT_FIELDS)
    explanation = read(client, token, f"/runs/{run_id}").json()["partial_explanation"]
    assert "stopped while drafting the assessment" in explanation
    assert "procurement recommendations" in explanation


def test_a_reviewed_statement_of_a_partial_run_stays_and_the_run_stays_partial(
    client: TestClient, engine: Engine
) -> None:
    organisation_id, run_id, facts = assessed_run(engine)
    quality = facts["quality_management"]
    adapter = BilledText([answer(strength(quality)), answer(priority(quality))])
    providers = providers_for(engine, structuring=adapter, budget=allow(1))
    execute_run(environment(engine, pipeline(assessment=assessment_stage()), providers), run_id)
    token = member(client, engine, organisation_id)
    path = f"/runs/{run_id}/assessment"
    item = read(client, token, path).json()["items"][0]

    reviewed = send_with_session(
        client,
        "PATCH",
        f"/assessment-statements/{item['id']}",
        token,
        json={"status": "corrected", "text": "My wording.", "version": item["version"]},
        headers={"Origin": LOCAL_ORIGIN},
    )
    assert reviewed.status_code == 200, reviewed.text
    execute_run(environment(engine, pipeline(assessment=assessment_stage()), providers), run_id)

    run = get_run(engine, run_id)
    body = read(client, token, path).json()
    assert run.status == "partial" and len(adapter.calls) == 1  # no new call, nothing replaced
    assert body["status"] == "partial"
    assert [(i["text"], i["provenance"]["status"]) for i in body["items"]] == [
        ("My wording.", "corrected")
    ]
    explanation = read(client, token, f"/runs/{run_id}").json()["partial_explanation"]
    assert "procurement recommendations" in explanation


def test_a_budget_reached_before_any_statement_lists_the_assessment_and_keeps_the_facts(
    client: TestClient, engine: Engine
) -> None:
    organisation_id, run_id, _facts = assessed_run(engine)
    adapter = BilledText([answer(), answer()])
    providers = providers_for(engine, structuring=adapter, budget=allow(0))

    execute_run(environment(engine, pipeline(assessment=assessment_stage()), providers), run_id)

    run = get_run(engine, run_id)
    assert run.status == "partial" and adapter.calls == []
    assert run.uncovered_sections == [*ASSESSMENT_SECTIONS, "recommendations"]
    token = member(client, engine, organisation_id)
    body = read(client, token, f"/runs/{run_id}/assessment").json()
    assert body["status"] == "partial" and body["items"] == []  # never "pending" for ever
    assert len(read(client, token, f"/runs/{run_id}/facts").json()["items"]) == len(FACT_FIELDS)


def test_a_natural_person_business_is_never_listed_as_an_uncovered_assessment(
    engine: Engine,
) -> None:
    organisation_id, run_id = extraction_run(engine)
    set_identity(engine, run_id, natural_person=True)
    providers = providers_for(
        engine, structuring=Billed(outputs=[], respond=respond), budget=allow(1)
    )

    execute_run(environment(engine, pipeline(extraction=extraction_stage()), providers), run_id)

    run = get_run(engine, run_id)
    assert run.status == "partial"
    assert run.uncovered_sections == FACT_SECTIONS[1:]  # not assessed by design, not by budget
    del organisation_id


# --- pauses, resumes and the budget -----------------------------------------------------------


def test_an_outage_pause_keeps_the_cost_so_far_and_the_resumed_run_stops_at_the_budget(
    client: TestClient, engine: Engine
) -> None:
    organisation_id, run_id = extraction_run(engine)
    state = {"outage": True}

    def flaky(asked: Asked) -> Any:
        if "production_sites" in asked.fields and state["outage"]:
            return ProviderCallError(provider="google", config_id="primary", kind="unavailable")
        return respond(asked)

    adapter = Billed(outputs=[], respond=flaky)
    providers = providers_for(engine, structuring=adapter, budget=allow(2))
    env = environment(engine, pipeline(extraction=extraction_stage()), providers)

    execute_run(env, run_id)

    paused = get_run(engine, run_id)
    assert paused.status == "paused" and paused.pause_dependency == "structuring_provider"
    assert paused.uncovered_sections == [] and paused.partial_explanation is None
    assert total_cost(engine, run_id) == CALL_COST  # one section done, the outage billed nothing
    token = member(client, engine, organisation_id)
    resumed = send_with_session(client, "POST", f"/runs/{run_id}/resume", token)
    assert resumed.status_code == 202
    state["outage"] = False

    execute_run(env, run_id)

    run = get_run(engine, run_id)
    assert run.status == "partial" and run.counts_against_quota is True
    assert total_cost(engine, run_id) == CALL_COST * 2  # the budget carried over the pause
    assert run.uncovered_sections == [FACT_SECTIONS[2], *ASSESSMENT_SECTIONS, "recommendations"]
    assert set(facts_of(engine, run_id)) >= {"production_sites", "founding_year"}


def test_a_redaction_failure_pauses_without_spending_and_the_budget_applies_on_resume(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    organisation_id, run_id = extraction_run(engine)
    adapter = Billed(outputs=[], respond=respond)
    providers = providers_for(engine, structuring=adapter, budget=allow(1))
    env = environment(engine, pipeline(extraction=extraction_stage()), providers)

    class Failing(RedactionGate):
        def redact(self, text: str, **_: Any) -> Any:
            raise RedactionUnavailable

    with monkeypatch.context() as patched:
        patched.setattr("app.extraction.stage.gate_for", lambda _db: Failing(lambda: ()))
        execute_run(env, run_id)

    paused = get_run(engine, run_id)
    assert paused.status == "paused" and paused.pause_reason == RedactionUnavailable.REASON
    assert adapter.asked == [] and total_cost(engine, run_id) == 0  # nothing sent, nothing billed
    token = member(client, engine, organisation_id)
    send_with_session(client, "POST", f"/runs/{run_id}/resume", token)

    execute_run(env, run_id)

    run = get_run(engine, run_id)
    assert run.status == "partial" and len(adapter.asked) == 1  # one call fitted, the next did not


def test_a_paused_run_whose_budget_is_already_spent_ends_partial_on_resume_without_a_call(
    client: TestClient, engine: Engine
) -> None:
    organisation_id, run_id = extraction_run(engine)
    with Session(engine) as db:
        db.execute(update(ProfileRun).where(ProfileRun.id == run_id).values(status="paused"))
        db.commit()
    add_usage(engine, organisation_id, run_id, cost="0.3")  # two rows: 0.6 EUR, above the budget
    adapter = Billed(outputs=[], respond=respond)
    providers = providers_for(engine, structuring=adapter, budget=Decimal("0.45"))
    token = member(client, engine, organisation_id)
    send_with_session(client, "POST", f"/runs/{run_id}/resume", token)

    execute_run(environment(engine, pipeline(extraction=extraction_stage()), providers), run_id)

    run = get_run(engine, run_id)
    assert run.status == "partial" and adapter.asked == []
    assert run.uncovered_sections == [*FACT_SECTIONS, *ASSESSMENT_SECTIONS, "recommendations"]


# --- the quota, and no later call ---------------------------------------------------------------


def test_a_partial_run_counts_against_the_quota(engine: Engine) -> None:
    organisation_id, run_id = extraction_run(engine)
    with Session(engine) as db:
        db.execute(
            update(Organisation).where(Organisation.id == organisation_id).values(profile_quota=1)
        )
        db.commit()
    providers = providers_for(
        engine, structuring=Billed(outputs=[], respond=respond), budget=allow(1)
    )

    execute_run(environment(engine, pipeline(extraction=extraction_stage()), providers), run_id)

    with Session(engine) as db:
        organisation = db.get(Organisation, organisation_id)
        assert organisation is not None
        assert profiles_remaining(db, organisation) == 0
    assert get_run(engine, run_id).status == "partial"


def test_no_drafting_is_queued_for_a_partial_run_or_one_that_billed_its_budget(
    engine: Engine,
) -> None:
    organisation_id, run_id, _facts = assessed_run(engine)
    with Session(engine) as db:
        db.execute(
            update(ProfileRun)
            .where(ProfileRun.id == run_id)
            .values(status="partial", assessment_drafted_at=ProfileRun.created_at)
        )
        db.commit()
    other = create_run(engine, organisation_id, status="completed", enqueue=False)
    with Session(engine) as db:
        db.execute(
            update(ProfileRun)
            .where(ProfileRun.id == other)
            .values(assessment_drafted_at=ProfileRun.created_at)
        )
        db.commit()
    add_usage(engine, organisation_id, other, cost="0.3")  # 0.6 EUR billed
    settings = Settings(
        database_url=None, allowed_origins=(LOCAL_ORIGIN,), run_budget_eur=Decimal("0.5")
    )
    client = make_client(settings=settings, engine=engine)
    token = member(client, engine, organisation_id)

    for target in (run_id, other):
        refused = send_with_session(client, "POST", f"/runs/{target}/recommendations", token)
        assert refused.status_code == 409
        assert refused.json() == {
            "detail": "The run reached its cost budget; no further AI call is made for it."
        }
        assert_matches_contract(refused, "/runs/{id}/recommendations", "post")
    with Session(engine) as db:
        assert db.scalars(select(Job)).all() == []  # nothing queued
        assert db.scalars(select(AssessmentItem).where(AssessmentItem.run_id == other)).all() == []


def test_a_run_that_did_not_reach_its_budget_still_reports_no_uncovered_section(
    client: TestClient, engine: Engine
) -> None:
    organisation_id, run_id = extraction_run(engine)
    providers = providers_for(
        engine, structuring=Billed(outputs=[], respond=respond), budget=allow(10)
    )

    execute_run(environment(engine, pipeline(extraction=extraction_stage()), providers), run_id)

    token = member(client, engine, organisation_id)
    response = read(client, token, f"/runs/{run_id}")
    assert_matches_contract(response, "/runs/{id}", "get")
    body = response.json()
    assert body["status"] == "completed"
    assert body["uncovered_sections"] == [] and body["partial_explanation"] is None
    assert json.loads(response.text)["usage"]["cost"] == "0.81000000"
