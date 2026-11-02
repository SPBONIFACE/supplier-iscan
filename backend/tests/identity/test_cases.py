"""The three named evaluation cases of #16, as recorded fixtures (`tests/identity/cases/*.json`).

NOT YET IN THE #22 HARNESS: #22 is not built. The fixtures are in a plain data format (inputs,
recorded registry answers, recorded model outputs, expectations) that the harness can load later.
Here they run against the fake provider: they prove the plumbing, not the quality of any model.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import SupplierIdentity
from app.registries.ranking import rank_candidates
from tests.auth_support import send_with_session
from tests.factories import create_session, create_user
from tests.identity.support import FakeRegistries, candidate, found, make_harness

CASES = sorted((Path(__file__).parent / "cases").glob("*.json"))


def _registries(case: dict[str, Any]) -> FakeRegistries:
    candidates = [candidate(**fields) for fields in case["registry"]["candidates"]]
    if case["registry"].get("rank"):
        return FakeRegistries(lambda query: found(*rank_candidates(query, candidates)))
    return FakeRegistries(found(*candidates))


def test_the_three_named_cases_are_present() -> None:
    assert {path.stem for path in CASES} == {
        "happy_path",
        "off_topic_declined",
        "homonym_contradicting_hint",
    }


@pytest.mark.parametrize("path", CASES, ids=lambda path: path.stem)
def test_recorded_case(path: Path, engine: Engine, settings: Settings) -> None:
    case = json.loads(path.read_text(encoding="utf-8"))
    outputs = [json.dumps(step["model_output"]) for step in case["steps"] if "model_output" in step]
    registries = _registries(case)
    harness = make_harness(engine, settings, registries, outputs)
    user = create_user(engine)
    token = create_session(engine, user.id)
    client = harness.client
    session: dict[str, Any] = {}
    searches_before = 0

    def call(method: str, path: str, **kwargs: Any) -> Any:
        return send_with_session(client, method, path, token, **kwargs)

    for step in case["steps"]:
        expect = step["expect"]
        if step["op"] == "create":
            body = {
                "name": case["input"]["name"],
                "hints": case["input"]["hints"],
                "profile_language": case["language"],
                "ui_language": case["language"],
            }
            response = call("POST", "/identity-sessions", json=body)
            assert response.status_code == 201, response.text
            session = response.json()
        elif step["op"] == "message":
            searches_before = len(registries.queries)
            response = call(
                "POST", f"/identity-sessions/{session['id']}/messages", json={"text": step["text"]}
            )
            assert response.status_code == 200, response.text
            previous_proposals = [t for t in session["turns"] if t["kind"] == "proposal"]
            session = response.json()
        elif step["op"] == "confirm":
            response = call(
                "POST",
                f"/identity-sessions/{session['id']}/confirm",
                json={"candidate_id": step["candidate_id"]},
            )
            assert response.status_code == expect["status"], response.text
            assert response.json()["candidate"]["legal_name"] == expect["legal_name"]
            assert response.json()["natural_person"] is expect["natural_person"]
            with Session(engine) as db:
                stored = db.scalars(select(SupplierIdentity)).one()
            assert stored.legal_name == expect["legal_name"] and stored.confirmed_at is not None
            continue

        turns = session["turns"]
        if "first_turn_kind" in expect:
            assert turns[0]["kind"] == expect["first_turn_kind"]
        assert turns[-1]["kind"] == expect["last_turn_kind"]
        if "proposed" in expect:
            assert turns[-1]["candidate"]["legal_name"] == expect["proposed"]
        if "last_turn_contains" in expect:
            assert expect["last_turn_contains"] in turns[-1]["text"]
        if expect.get("no_new_proposal"):
            assert [t for t in turns if t["kind"] == "proposal"] == previous_proposals
        if "searches" in expect:
            assert len(registries.queries) == expect["searches"]
            assert len(registries.queries) == searches_before
        if "other_candidates" in expect:
            others = call("GET", f"/identity-sessions/{session['id']}/candidates").json()
            assert len(others["candidates"]) == expect["other_candidates"]
        if "all_candidates_in_search" in expect:
            ranked = [t for t in turns if t["kind"] == "proposal"][0]
            assert ranked["candidate"]["legal_name"] == expect["first_candidate_in_search"]
            others = call("GET", f"/identity-sessions/{session['id']}/candidates").json()
            names = [ranked["candidate"]["legal_name"]] + [
                c["legal_name"] for c in others["candidates"]
            ]
            assert sorted(names) == sorted(expect["all_candidates_in_search"])
