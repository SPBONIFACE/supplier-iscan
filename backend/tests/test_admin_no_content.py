"""A hosted administrator sees no profile content and starts no work on it (#203; spec, Security
model: access rules). Self-hosted instances are unchanged: the local administrator reads and runs
in the default organisation.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AssessmentItem, Fact, IdentitySession
from app.organisations.scope import MEMBERS_ONLY, require_member_content_scope
from tests.auth_support import send_with_session
from tests.contract.test_auth_contract import assert_matches_contract
from tests.factories import create_organisation, create_session, create_user
from tests.pdf.db_support import finished_run
from tests.runs_support import create_identity
from tests.support import make_client
from tests.test_route_access import _calls, application, routes_of

MARKER = "Distinctive Supplier SA"
MEMBERS_ONLY_BODY = {"detail": MEMBERS_ONLY, "reason": "members_only"}

# Every operation that reads or writes profile content, or starts work on it: (method, path).
CONTENT_OPERATIONS = {
    ("POST", "/identity-sessions"),
    ("GET", "/identity-sessions/{id}"),
    ("POST", "/identity-sessions/{id}/messages"),
    ("GET", "/identity-sessions/{id}/candidates"),
    ("POST", "/identity-sessions/{id}/website"),
    ("POST", "/identity-sessions/{id}/confirm"),
    ("POST", "/runs"),
    ("GET", "/runs/{id}/sources"),
    ("GET", "/runs/{id}/facts"),
    ("GET", "/runs/{id}/assessment"),
    ("PUT", "/runs/{id}/criteria"),
    ("POST", "/runs/{id}/fit"),
    ("PUT", "/runs/{id}/buyer-context"),
    ("POST", "/runs/{id}/recommendations"),
    ("GET", "/runs/{id}/buyer-inputs"),
    ("PUT", "/runs/{id}/buyer-inputs/{field}"),
    ("GET", "/runs/{id}/pdf"),
    ("POST", "/runs/{id}/resume"),
    ("GET", "/comparison"),
    ("PATCH", "/facts/{id}"),
    ("PATCH", "/assessment-statements/{id}"),
}

# The content operations that only read, which a member (and a self-hosted administrator) gets.
READS = sorted(
    (method, path)
    for method, path in CONTENT_OPERATIONS
    if method == "GET" and path != "/runs/{id}/pdf"
)


@dataclass(frozen=True)
class Content:
    """One organisation's profile content, and a session on it for each kind of user."""

    run_id: uuid.UUID
    other_run_id: uuid.UUID
    identity_id: uuid.UUID
    session_id: uuid.UUID
    fact_id: uuid.UUID
    statement_id: uuid.UUID
    admin: str
    member: str

    def path(self, template: str) -> str:
        if template == "/comparison":
            return f"/comparison?run_ids={self.run_id}&run_ids={self.other_run_id}"
        if template.startswith("/identity-sessions/"):
            return template.replace("{id}", str(self.session_id))
        if template == "/facts/{id}":
            return f"/facts/{self.fact_id}"
        if template == "/assessment-statements/{id}":
            return f"/assessment-statements/{self.statement_id}"
        return template.replace("{id}", str(self.run_id)).replace("{field}", "notes")


def make_content(engine: Engine) -> Content:
    organisation_id = create_organisation(engine)
    run_id = finished_run(engine, organisation_id, MARKER)
    other_run_id = finished_run(engine, organisation_id, "Second Supplier SA")
    identity_id = create_identity(engine, organisation_id, legal_name=MARKER)
    with Session(engine) as db:
        session = IdentitySession(
            organisation_id=organisation_id,
            name=MARKER,
            hints={},
            profile_language="en",
            ui_language="en",
            transcript=[
                {
                    "id": "turn-1",
                    "role": "user",
                    "kind": "text",
                    "text": MARKER,
                    "candidate": None,
                    "created_at": "2026-11-16T09:00:00+00:00",
                }
            ],
            candidates=[],
            registries={},
        )
        statement = AssessmentItem(
            organisation_id=organisation_id,
            run_id=run_id,
            position=0,
            kind="strength",
            text=f"{MARKER} is well established.",
            provider="google",
            model_id="gemini-flash-eu-01",
            model_version="2026-09",
            prompt_id="assessment",
            prompt_version="3",
            generated_at=datetime(2026, 10, 14, 9, 42, tzinfo=UTC),
            status="ai_draft",
        )
        db.add_all([session, statement])
        db.commit()
        fact_id = db.scalars(select(Fact.id).where(Fact.run_id == run_id)).first()
        assert fact_id is not None
        session_id, statement_id = session.id, statement.id
    admin = create_user(engine, role="admin", organisation_id=organisation_id)
    member = create_user(engine, organisation_id=organisation_id)
    return Content(
        run_id=run_id,
        other_run_id=other_run_id,
        identity_id=identity_id,
        session_id=session_id,
        fact_id=fact_id,
        statement_id=statement_id,
        admin=create_session(engine, admin.id),
        member=create_session(engine, member.id),
    )


@pytest.fixture
def hosted(engine: Engine, settings: Settings) -> Iterator[TestClient]:
    yield make_client(settings=replace(settings, instance_mode="hosted"), engine=engine)


@pytest.fixture
def self_hosted(engine: Engine, settings: Settings) -> Iterator[TestClient]:
    yield make_client(settings=replace(settings, instance_mode="self_hosted"), engine=engine)


def send(client: TestClient, token: str, method: str, path: str) -> httpx2.Response:
    body: dict[str, Any] | None = {} if method in ("POST", "PUT", "PATCH") else None
    return send_with_session(client, method, path, token, json=body)


def test_every_content_operation_depends_on_the_member_content_scope() -> None:
    gated = {
        (method, route.path)
        for route in routes_of(application().routes)
        if isinstance(route.original_route, APIRoute)
        and require_member_content_scope in set(_calls(route.dependant))
        for method in route.methods or ()
    }

    assert gated == CONTENT_OPERATIONS


@pytest.mark.parametrize(("method", "template"), sorted(CONTENT_OPERATIONS))
def test_a_hosted_administrator_gets_403_on_every_content_operation(
    hosted: TestClient, engine: Engine, method: str, template: str
) -> None:
    content = make_content(engine)

    response = send(hosted, content.admin, method, content.path(template))

    assert response.status_code == 403, response.text
    assert response.json() == MEMBERS_ONLY_BODY
    assert MARKER not in response.text
    assert_matches_contract(response, template, method.lower())


def test_a_hosted_administrator_starts_no_run_with_a_valid_body(
    hosted: TestClient, engine: Engine
) -> None:
    content = make_content(engine)

    run = send_with_session(
        hosted, "POST", "/runs", content.admin, json={"identity_id": str(content.identity_id)}
    )
    session = send_with_session(
        hosted,
        "POST",
        "/identity-sessions",
        content.admin,
        json={"name": "Some Supplier", "profile_language": "en", "ui_language": "en"},
    )

    assert (run.status_code, session.status_code) == (403, 403)
    assert run.json() == session.json() == MEMBERS_ONLY_BODY
    assert_matches_contract(run, "/runs", "post")


def test_a_hosted_administrators_pdf_renders_nothing(hosted: TestClient, engine: Engine) -> None:
    content = make_content(engine)

    response = send(hosted, content.admin, "GET", f"/runs/{content.run_id}/pdf")

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/json")
    assert not response.content.startswith(b"%PDF")
    assert MARKER.encode() not in response.content
    assert "content-disposition" not in response.headers


def test_the_403_answers_the_same_for_a_resource_that_does_not_exist(
    hosted: TestClient, engine: Engine
) -> None:
    content = make_content(engine)

    missing = send(hosted, content.admin, "GET", f"/runs/{uuid.uuid4()}/facts")

    assert missing.status_code == 403
    assert missing.json() == MEMBERS_ONLY_BODY


@pytest.mark.parametrize(("method", "template"), READS)
def test_a_member_of_the_same_organisation_reads_the_content(
    hosted: TestClient, engine: Engine, method: str, template: str
) -> None:
    content = make_content(engine)

    response = send(hosted, content.member, method, content.path(template))

    assert response.status_code == 200, response.text


@pytest.mark.parametrize(("method", "template"), sorted(CONTENT_OPERATIONS))
def test_a_member_is_never_refused_as_members_only(
    hosted: TestClient, engine: Engine, method: str, template: str
) -> None:
    content = make_content(engine)

    response = send(hosted, content.member, method, content.path(template))

    assert response.status_code != 403 or response.json().get("reason") != "members_only"


def test_a_member_reads_the_facts_and_the_card_content(hosted: TestClient, engine: Engine) -> None:
    content = make_content(engine)

    session = send(hosted, content.member, "GET", f"/identity-sessions/{content.session_id}")
    assessment = send(hosted, content.member, "GET", f"/runs/{content.run_id}/assessment")
    facts = send(hosted, content.member, "GET", f"/runs/{content.run_id}/facts")

    assert MARKER in session.text
    assert MARKER in assessment.text
    assert facts.json()["items"], facts.text


@pytest.mark.parametrize(("method", "template"), READS)
def test_a_self_hosted_administrator_reads_the_default_organisations_content(
    self_hosted: TestClient, engine: Engine, method: str, template: str
) -> None:
    content = make_content(engine)

    response = send(self_hosted, content.admin, method, content.path(template))

    assert response.status_code == 200, response.text


def test_a_self_hosted_administrator_starts_an_identity_session_and_a_run(
    self_hosted: TestClient, engine: Engine
) -> None:
    content = make_content(engine)

    run = send_with_session(
        self_hosted, "POST", "/runs", content.admin, json={"identity_id": str(content.identity_id)}
    )

    assert run.status_code == 202, run.text
    assert run.json()["supplier_name"] == MARKER


def test_the_hosted_administrators_organisation_says_runs_are_for_members(
    hosted: TestClient, self_hosted: TestClient, engine: Engine
) -> None:
    content = make_content(engine)

    admin = send(hosted, content.admin, "GET", "/organisation")
    member = send(hosted, content.member, "GET", "/organisation")
    local = send(self_hosted, content.admin, "GET", "/organisation")

    assert admin.json()["run_refusal_reason"] == "members_only"
    assert member.json()["run_refusal_reason"] is None
    assert local.json()["run_refusal_reason"] is None
    assert_matches_contract(admin, "/organisation", "get")


def test_a_hosted_administrator_keeps_the_run_list_without_names(
    hosted: TestClient, engine: Engine
) -> None:
    content = make_content(engine)

    runs = send(hosted, content.admin, "GET", "/runs")
    one = send(hosted, content.admin, "GET", f"/runs/{content.run_id}")
    failures = send(hosted, content.admin, "GET", f"/runs/{content.run_id}/failures")

    assert (runs.status_code, one.status_code, failures.status_code) == (200, 200, 200)
    assert MARKER not in runs.text + one.text
    assert {item["status"] for item in runs.json()["items"]} == {"completed"}
