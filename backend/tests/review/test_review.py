"""Review of facts and assessment statements (#28): approve, correct, delete, who and when, the
original AI value kept, concurrent edits (409), the run still in progress, the count of proposed
facts, isolation and the contract. No model is called."""

import threading
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import utc_now
from app.models import AssessmentItem, Fact
from tests.auth_support import send_with_session
from tests.contract.test_auth_contract import assert_matches_contract
from tests.factories import TestUser, create_organisation, create_session, create_user
from tests.isolation_support import OwnedResource, OwnerOrganisation, assert_organisation_isolation
from tests.runs_support import create_run
from tests.support import LOCAL_ORIGIN, make_client

AI_VALUE = "ISO 14001"
AI_QUOTE = "We hold ISO 14001 certification"
AI_TEXT = "The environmental system is certified, per the supplier's own claim."


class Reviewed:
    """A finished run with two proposed facts, one fact without evidence and two statements."""

    def __init__(self, engine: Engine, status: str = "completed") -> None:
        self.engine = engine
        self.user: TestUser = create_user(engine)
        self.organisation_id = self.user.organisation_id
        self.token = create_session(engine, self.user.id)
        self.run_id = create_run(engine, self.organisation_id, status=status, enqueue=False)
        self.environmental = self.fact("environmental_management", "proposed", AI_VALUE, AI_QUOTE)
        self.founding = self.fact("founding_year", "proposed", "2005", "was founded in 2005")
        self.missing = self.fact("legal_form", "not_found", None, None)
        self.statement = self.add_statement(AI_TEXT)
        self.other_statement = self.add_statement("A second statement.")

    def fact(self, field: str, status: str, value: str | None, quote: str | None) -> uuid.UUID:
        with Session(self.engine) as db:
            fact = Fact(
                run_id=self.run_id,
                organisation_id=self.organisation_id,
                section="company_overview",
                field=field,
                status=status,
                value=value,
                quote=quote,
                source_url="https://www.acme.example/about" if value else None,
                source_type="supplier_claim" if value else None,
            )
            db.add(fact)
            db.commit()
            return fact.id

    def add_statement(self, text: str) -> uuid.UUID:
        with Session(self.engine) as db:
            position = len(list(db.scalars(select(AssessmentItem.id)))) + 1
            row = AssessmentItem(
                run_id=self.run_id,
                organisation_id=self.organisation_id,
                position=position,
                kind="strength",
                text=text,
                cited_fact_ids=[str(self.environmental)],
                provider="google",
                model_id="model-1",
                model_version="primary",
                prompt_id="assessment",
                prompt_version="1",
                generated_at=utc_now(),
            )
            db.add(row)
            db.commit()
            return row.id

    def patch(
        self, client: TestClient, path: str, body: dict[str, Any], token: str | None = None
    ) -> Any:
        return send_with_session(client, "PATCH", path, token or self.token, json=body)

    def review_fact(
        self, client: TestClient, fact_id: uuid.UUID, body: dict[str, Any], token: str | None = None
    ) -> Any:
        return self.patch(client, f"/facts/{fact_id}", body, token)

    def review_statement(
        self, client: TestClient, id: uuid.UUID, body: dict[str, Any], token: str | None = None
    ) -> Any:
        return self.patch(client, f"/assessment-statements/{id}", body, token)

    def get(self, client: TestClient, tail: str) -> Any:
        return send_with_session(client, "GET", f"/runs/{self.run_id}{tail}", self.token)

    def fact_row(self, fact_id: uuid.UUID) -> Fact:
        with Session(self.engine) as db:
            return db.scalars(select(Fact).where(Fact.id == fact_id)).one()

    def statement_row(self, id: uuid.UUID) -> AssessmentItem:
        with Session(self.engine) as db:
            return db.scalars(select(AssessmentItem).where(AssessmentItem.id == id)).one()


def proposed(client: TestClient, reviewed: Reviewed) -> int:
    response = reviewed.get(client, "")
    assert_matches_contract(response, "/runs/{id}", "get")
    return int(response.json()["proposed_facts"])


# --- facts -----------------------------------------------------------------------------------


def test_a_member_approves_a_fact_and_the_proposed_count_falls(
    client: TestClient, engine: Engine
) -> None:
    reviewed = Reviewed(engine)
    assert proposed(client, reviewed) == 2

    response = reviewed.review_fact(
        client, reviewed.environmental, {"status": "approved", "version": 1}
    )

    assert response.status_code == 200
    assert_matches_contract(response, "/facts/{id}", "patch")
    body = response.json()
    assert body["status"] == "approved" and body["version"] == 2
    assert body["reviewed_by"] == str(reviewed.user.id) and body["reviewed_at"]
    assert body["value"] == AI_VALUE and body["original_value"] is None
    assert body["quote"] == AI_QUOTE and body["source_url"] == "https://www.acme.example/about"
    assert proposed(client, reviewed) == 1
    listed = {e["field"]: e for e in reviewed.get(client, "/facts").json()["items"]}
    assert listed["environmental_management"]["status"] == "approved"
    assert_matches_contract(reviewed.get(client, "/facts"), "/runs/{id}/facts", "get")


def test_a_correction_keeps_the_ai_value_and_quote_and_a_second_keeps_the_original(
    client: TestClient, engine: Engine
) -> None:
    reviewed = Reviewed(engine)

    first = reviewed.review_fact(
        client,
        reviewed.environmental,
        {"status": "corrected", "value": "  ISO 14001:2015 ", "version": 1},
    )
    second = reviewed.review_fact(
        client,
        reviewed.environmental,
        {"status": "corrected", "value": "ISO 14001 and ISO 45001", "version": 2},
    )

    assert first.status_code == 200 and second.status_code == 200
    assert_matches_contract(second, "/facts/{id}", "patch")
    one, two = first.json(), second.json()
    assert one["status"] == "corrected" and one["value"] == "ISO 14001:2015"
    assert one["original_value"] == AI_VALUE and one["quote"] == AI_QUOTE
    assert two["value"] == "ISO 14001 and ISO 45001" and two["version"] == 3
    assert two["original_value"] == AI_VALUE and two["quote"] == AI_QUOTE  # kept, not replaced
    assert two["reviewed_by"] == str(reviewed.user.id)
    row = reviewed.fact_row(reviewed.environmental)
    assert row.original_value == AI_VALUE and row.quote == AI_QUOTE and row.source_id is None
    assert proposed(client, reviewed) == 1  # a corrected fact is no longer proposed


def test_a_correction_after_an_approval_keeps_the_ai_value(
    client: TestClient, engine: Engine
) -> None:
    reviewed = Reviewed(engine)
    reviewed.review_fact(client, reviewed.founding, {"status": "approved", "version": 1})

    response = reviewed.review_fact(
        client, reviewed.founding, {"status": "corrected", "value": "2006", "version": 2}
    )

    assert response.json()["original_value"] == "2005" and response.json()["value"] == "2006"


def test_a_blank_or_misplaced_value_is_refused_with_422_and_never_echoed(
    engine: Engine,
) -> None:
    reviewed = Reviewed(engine)
    client = make_client(
        settings=Settings(
            database_url=None, allowed_origins=(LOCAL_ORIGIN,), review_text_max_chars=10
        ),
        engine=engine,
    )
    fact = reviewed.environmental
    bad: list[dict[str, Any]] = [
        {"status": "corrected", "value": "", "version": 1},
        {"status": "corrected", "value": "   ", "version": 1},
        {"status": "corrected", "value": None, "version": 1},
        {"status": "corrected", "version": 1},
        {"status": "corrected", "value": "Anna Keller-Brandt is far too long", "version": 1},
        {"status": "approved", "value": "Anna Keller-Brandt", "version": 1},
        {"status": "rejected", "version": 1},
        {"status": "approved", "version": 0},
        {"status": "approved"},
    ]

    for body in bad:
        response = reviewed.review_fact(client, fact, body)
        assert response.status_code == 422, body
        assert "Anna Keller-Brandt" not in response.text
        assert_matches_contract(response, "/facts/{id}", "patch")

    fits = reviewed.review_fact(
        client, fact, {"status": "corrected", "value": "x" * 10, "version": 1}
    )
    assert fits.status_code == 200
    assert reviewed.fact_row(fact).version == 2  # only the valid request wrote


def test_a_fact_without_evidence_has_nothing_to_review(client: TestClient, engine: Engine) -> None:
    reviewed = Reviewed(engine)

    approve = reviewed.review_fact(client, reviewed.missing, {"status": "approved", "version": 1})
    correct = reviewed.review_fact(
        client, reviewed.missing, {"status": "corrected", "value": "SA", "version": 1}
    )

    for response in (approve, correct):
        assert response.status_code == 409
        assert_matches_contract(response, "/facts/{id}", "patch")
        assert "No public evidence found" in response.json()["detail"]
    row = reviewed.fact_row(reviewed.missing)
    assert row.status == "not_found" and row.value is None and row.version == 1


def test_a_corrected_fact_is_not_approved_over_the_correction(
    client: TestClient, engine: Engine
) -> None:
    reviewed = Reviewed(engine)
    reviewed.review_fact(
        client, reviewed.founding, {"status": "corrected", "value": "2006", "version": 1}
    )

    response = reviewed.review_fact(client, reviewed.founding, {"status": "approved", "version": 2})

    assert response.status_code == 409
    row = reviewed.fact_row(reviewed.founding)
    assert row.status == "corrected" and row.value == "2006" and row.original_value == "2005"


def test_approving_twice_at_the_current_version_records_nothing_new(
    client: TestClient, engine: Engine
) -> None:
    reviewed = Reviewed(engine)
    reviewed.review_fact(client, reviewed.founding, {"status": "approved", "version": 1})
    before = reviewed.fact_row(reviewed.founding)

    again = reviewed.review_fact(client, reviewed.founding, {"status": "approved", "version": 2})

    after = reviewed.fact_row(reviewed.founding)
    assert (
        again.status_code == 200 and after.version == 2 and after.reviewed_at == before.reviewed_at
    )


# --- concurrent edits ------------------------------------------------------------------------


def test_a_review_based_on_an_outdated_version_returns_409_with_the_current_fact(
    client: TestClient, engine: Engine
) -> None:
    reviewed = Reviewed(engine)
    colleague = create_user(engine, organisation_id=reviewed.organisation_id)
    other = create_session(engine, colleague.id)
    saved = reviewed.review_fact(
        client,
        reviewed.environmental,
        {"status": "corrected", "value": "First correction", "version": 1},
        other,
    )

    stale = reviewed.review_fact(
        client,
        reviewed.environmental,
        {"status": "corrected", "value": "Lost edit", "version": 1},
    )
    ahead = reviewed.review_fact(
        client, reviewed.environmental, {"status": "approved", "version": 9}
    )

    assert saved.status_code == 200 and stale.status_code == 409 and ahead.status_code == 409
    assert_matches_contract(stale, "/facts/{id}", "patch")
    current = stale.json()["current"]
    assert current["value"] == "First correction" and current["version"] == 2
    assert current["original_value"] == AI_VALUE and current["reviewed_by"] == str(colleague.id)
    assert "Lost edit" not in reviewed.fact_row(reviewed.environmental).value  # type: ignore[operator]
    retry = reviewed.review_fact(
        client,
        reviewed.environmental,
        {"status": "corrected", "value": "Merged", "version": current["version"]},
    )
    assert retry.status_code == 200 and retry.json()["original_value"] == AI_VALUE


def test_two_simultaneous_corrections_never_lose_the_ai_value(engine: Engine) -> None:
    reviewed = Reviewed(engine)
    colleague = create_user(engine, organisation_id=reviewed.organisation_id)
    tokens = [reviewed.token, create_session(engine, colleague.id)]
    clients = [make_client(engine=engine), make_client(engine=engine)]
    barrier = threading.Barrier(2)
    answers: list[Any] = [None, None]

    def correct(index: int) -> None:
        barrier.wait()
        answers[index] = reviewed.review_fact(
            clients[index],
            reviewed.environmental,
            {"status": "corrected", "value": f"Value {index}", "version": 1},
            tokens[index],
        )

    threads = [threading.Thread(target=correct, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    codes = sorted(answer.status_code for answer in answers)
    assert codes == [200, 409]
    row = reviewed.fact_row(reviewed.environmental)
    assert row.original_value == AI_VALUE and row.quote == AI_QUOTE
    assert row.version == 2 and row.value in ("Value 0", "Value 1")
    winner = next(a for a in answers if a.status_code == 200)
    loser = next(a for a in answers if a.status_code == 409)
    assert loser.json()["current"]["value"] == winner.json()["value"]


# --- the run must have finished --------------------------------------------------------------


@pytest.mark.parametrize("status", ["queued", "running", "paused"])
def test_a_review_on_a_run_in_progress_returns_409_and_writes_nothing(
    client: TestClient, engine: Engine, status: str
) -> None:
    reviewed = Reviewed(engine, status=status)

    fact = reviewed.review_fact(client, reviewed.founding, {"status": "approved", "version": 1})
    statement = reviewed.review_statement(
        client, reviewed.statement, {"status": "deleted", "version": 1}
    )

    for response, path in ((fact, "/facts/{id}"), (statement, "/assessment-statements/{id}")):
        assert response.status_code == 409
        assert response.json() == {"detail": "The run is still in progress."}
        assert_matches_contract(response, path, "patch")
    assert reviewed.fact_row(reviewed.founding).status == "proposed"
    assert reviewed.statement_row(reviewed.statement).status == "ai_draft"


@pytest.mark.parametrize("status", ["completed", "partial", "stopped", "failed"])
def test_a_finished_run_can_be_reviewed(client: TestClient, engine: Engine, status: str) -> None:
    reviewed = Reviewed(engine, status=status)

    response = reviewed.review_fact(client, reviewed.founding, {"status": "approved", "version": 1})

    assert response.status_code == 200


# --- statements ------------------------------------------------------------------------------


def test_a_statement_is_an_ai_draft_until_a_member_decides(
    client: TestClient, engine: Engine
) -> None:
    reviewed = Reviewed(engine)
    reviewed.review_fact(client, reviewed.environmental, {"status": "approved", "version": 1})

    body = reviewed.get(client, "/assessment").json()

    assert_matches_contract(reviewed.get(client, "/assessment"), "/runs/{id}/assessment", "get")
    for item in body["items"]:  # reviewing a fact does not review the statements that cite it
        assert item["provenance"]["status"] == "ai_draft"
        assert (
            item["provenance"]["reviewed_by"] is None and item["provenance"]["reviewed_at"] is None
        )
        assert item["version"] == 1 and item["original_text"] is None

    approved = reviewed.review_statement(
        client, reviewed.statement, {"status": "approved", "version": 1}
    )

    assert approved.status_code == 200
    assert_matches_contract(approved, "/assessment-statements/{id}", "patch")
    provenance = approved.json()["provenance"]
    assert provenance["status"] == "approved" and provenance["reviewed_by"] == str(reviewed.user.id)
    assert provenance["reviewed_at"] and provenance["provider"] == "google"
    statuses = {
        i["id"]: i["provenance"]["status"]
        for i in reviewed.get(client, "/assessment").json()["items"]
    }
    assert statuses[str(reviewed.statement)] == "approved"
    assert statuses[str(reviewed.other_statement)] == "ai_draft"


def test_a_statement_correction_keeps_the_ai_text_and_its_provenance(
    client: TestClient, engine: Engine
) -> None:
    reviewed = Reviewed(engine)
    before = reviewed.statement_row(reviewed.statement)

    first = reviewed.review_statement(
        client, reviewed.statement, {"status": "corrected", "text": " My wording. ", "version": 1}
    )
    second = reviewed.review_statement(
        client,
        reviewed.statement,
        {"status": "corrected", "text": "My final wording.", "version": 2},
    )

    assert first.status_code == 200 and second.status_code == 200
    assert_matches_contract(second, "/assessment-statements/{id}", "patch")
    assert first.json()["text"] == "My wording." and first.json()["original_text"] == AI_TEXT
    body = second.json()
    assert body["text"] == "My final wording." and body["original_text"] == AI_TEXT
    assert body["version"] == 3 and body["provenance"]["status"] == "corrected"
    after = reviewed.statement_row(reviewed.statement)
    for column in ("provider", "model_id", "model_version", "prompt_id", "prompt_version"):
        assert getattr(after, column) == getattr(before, column)
    assert (
        after.generated_at == before.generated_at and after.cited_fact_ids == before.cited_fact_ids
    )


def test_a_deleted_statement_keeps_its_row_and_provenance_but_is_not_returned(
    client: TestClient, engine: Engine
) -> None:
    reviewed = Reviewed(engine)

    deleted = reviewed.review_statement(
        client, reviewed.statement, {"status": "deleted", "version": 1}
    )

    assert deleted.status_code == 200
    assert deleted.json()["provenance"]["status"] == "deleted"
    items = reviewed.get(client, "/assessment").json()["items"]
    assert [i["id"] for i in items] == [str(reviewed.other_statement)]
    row = reviewed.statement_row(reviewed.statement)
    assert row.status == "deleted" and row.text == AI_TEXT and row.provider == "google"
    assert row.reviewed_by == reviewed.user.id and row.reviewed_at is not None
    again = reviewed.review_statement(
        client, reviewed.statement, {"status": "approved", "version": 2}
    )
    assert again.status_code == 409 and again.json()["current"]["provenance"]["status"] == "deleted"
    assert_matches_contract(again, "/assessment-statements/{id}", "patch")


def test_a_statement_review_on_an_outdated_version_returns_409_with_the_current_one(
    client: TestClient, engine: Engine
) -> None:
    reviewed = Reviewed(engine)
    colleague = create_user(engine, organisation_id=reviewed.organisation_id)
    other = create_session(engine, colleague.id)
    reviewed.review_statement(
        client,
        reviewed.statement,
        {"status": "corrected", "text": "Colleague", "version": 1},
        other,
    )

    stale = reviewed.review_statement(
        client, reviewed.statement, {"status": "corrected", "text": "Lost", "version": 1}
    )

    assert stale.status_code == 409
    assert_matches_contract(stale, "/assessment-statements/{id}", "patch")
    current = stale.json()["current"]
    assert current["text"] == "Colleague" and current["original_text"] == AI_TEXT
    assert current["version"] == 2
    assert reviewed.statement_row(reviewed.statement).text == "Colleague"


def test_a_corrected_statement_is_not_approved_over_the_correction(
    client: TestClient, engine: Engine
) -> None:
    reviewed = Reviewed(engine)
    reviewed.review_statement(
        client, reviewed.statement, {"status": "corrected", "text": "Mine", "version": 1}
    )

    response = reviewed.review_statement(
        client, reviewed.statement, {"status": "approved", "version": 2}
    )

    assert response.status_code == 409
    assert reviewed.statement_row(reviewed.statement).status == "corrected"


def test_a_blank_or_misplaced_statement_text_is_refused_with_422_and_never_echoed(
    client: TestClient, engine: Engine
) -> None:
    reviewed = Reviewed(engine)
    bad: list[dict[str, Any]] = [
        {"status": "corrected", "text": "", "version": 1},
        {"status": "corrected", "text": "  \n ", "version": 1},
        {"status": "corrected", "version": 1},
        {"status": "deleted", "text": "Anna Keller-Brandt", "version": 1},
        {"status": "approved", "text": "Anna Keller-Brandt", "version": 1},
        {"status": "ai_draft", "version": 1},
    ]

    for body in bad:
        response = reviewed.review_statement(client, reviewed.statement, body)
        assert response.status_code == 422, body
        assert "Anna Keller-Brandt" not in response.text
        assert_matches_contract(response, "/assessment-statements/{id}", "patch")
    assert reviewed.statement_row(reviewed.statement).version == 1


# --- access ----------------------------------------------------------------------------------


def make_fact_resource(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
    user = create_user(engine, organisation_id=owner.id)
    run_id = create_run(engine, owner.id, status="completed", enqueue=False)
    reviewed = Reviewed.__new__(Reviewed)
    reviewed.engine, reviewed.organisation_id, reviewed.run_id = (
        engine,
        user.organisation_id,
        run_id,
    )
    fact_id = reviewed.fact(
        "founding_year", "proposed", "Distinctive 1987", "founded in Distinctive 1987"
    )
    return OwnedResource(
        path=f"/facts/{fact_id}", missing_path=f"/facts/{uuid.uuid4()}", marker="Distinctive 1987"
    )


def test_facts_are_reviewed_by_the_owning_organisation_only(
    client: TestClient, engine: Engine
) -> None:
    assert_organisation_isolation(
        client, engine, "PATCH", make_fact_resource, json={"status": "approved", "version": 1}
    )


def make_statement_resource(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
    user = create_user(engine, organisation_id=owner.id)
    run_id = create_run(engine, owner.id, status="completed", enqueue=False)
    reviewed = Reviewed.__new__(Reviewed)
    reviewed.engine, reviewed.organisation_id, reviewed.run_id = (
        engine,
        user.organisation_id,
        run_id,
    )
    reviewed.environmental = uuid.uuid4()
    statement_id = reviewed.add_statement("Distinctive statement 1987")
    return OwnedResource(
        path=f"/assessment-statements/{statement_id}",
        missing_path=f"/assessment-statements/{uuid.uuid4()}",
        marker="Distinctive statement 1987",
    )


def test_statements_are_reviewed_by_the_owning_organisation_only(
    client: TestClient, engine: Engine
) -> None:
    assert_organisation_isolation(
        client, engine, "PATCH", make_statement_resource, json={"status": "deleted", "version": 1}
    )


def test_another_organisation_cannot_review_and_nothing_is_written(
    client: TestClient, engine: Engine
) -> None:
    reviewed = Reviewed(engine)
    stranger = create_user(engine, organisation_id=create_organisation(engine))
    token = create_session(engine, stranger.id)

    fact = reviewed.review_fact(
        client, reviewed.founding, {"status": "corrected", "value": "x", "version": 1}, token
    )
    statement = reviewed.review_statement(
        client, reviewed.statement, {"status": "deleted", "version": 1}, token
    )

    assert fact.status_code == 404 and statement.status_code == 404
    assert reviewed.fact_row(reviewed.founding).status == "proposed"
    assert reviewed.statement_row(reviewed.statement).status == "ai_draft"


def test_a_malformed_id_answers_404(client: TestClient, engine: Engine) -> None:
    reviewed = Reviewed(engine)

    for path in ("/facts/not-a-uuid", "/assessment-statements/not-a-uuid"):
        response = reviewed.patch(client, path, {"status": "approved", "version": 1})
        assert response.status_code == 404
