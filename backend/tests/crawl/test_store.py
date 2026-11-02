"""#17: stored crawl permissions, the suppression list table, and what a run shows."""

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.crawl import (
    EXCLUSION_MESSAGE,
    DatabaseSuppressionList,
    DomainPermission,
    record_permission,
)
from app.db import Database, utc_now
from app.errors import NOT_FOUND
from app.models import CrawlPermission, SuppressionEntry
from tests.auth_support import send_with_session
from tests.factories import create_organisation, create_session, create_user
from tests.runs_support import create_run


def permission(domain: str, decision: str, **fields: object) -> DomainPermission:
    return DomainPermission(
        domain=domain,
        robots_result="found",
        decision=decision,  # type: ignore[arg-type]
        checked_at=utc_now(),
        **fields,  # type: ignore[arg-type]
    )


def test_a_permission_is_stored_once_per_run_and_domain_and_replaced_on_a_new_check(
    engine: Engine,
) -> None:
    database = Database(None, engine)
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id)

    record_permission(database, run_id, organisation_id, permission("a.example", "not_crawled"))
    record_permission(
        database,
        run_id,
        organisation_id,
        permission("a.example", "excluded", tdm_reservation=True),
    )

    with Session(engine) as db:
        (row,) = db.scalars(select(CrawlPermission)).all()
    assert (row.domain, row.decision, row.tdm_reservation, row.suppression_hit) == (
        "a.example",
        "excluded",
        True,
        False,
    )
    assert row.robots_result == "found" and row.checked_at is not None


def test_the_run_shows_the_exclusion_message_and_nothing_else_of_the_record(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    database = Database(None, engine)
    run_id = create_run(engine, user.organisation_id)
    record_permission(
        database,
        run_id,
        user.organisation_id,
        permission("b.example", "excluded", suppression_hit=True),
    )
    record_permission(database, run_id, user.organisation_id, permission("c.example", "allowed"))
    record_permission(database, run_id, user.organisation_id, permission("d.example", "blocked"))

    body = send_with_session(client, "GET", f"/runs/{run_id}", token).json()

    assert body["excluded_sources"] == [{"domain": "b.example", "message": EXCLUSION_MESSAGE}]
    assert "robots_result" not in str(body) and "suppression_hit" not in str(body)
    listed = send_with_session(client, "GET", "/runs", token).json()["items"][0]
    assert listed["excluded_sources"] == body["excluded_sources"]


def test_another_organisation_gets_404_and_no_exclusion(client: TestClient, engine: Engine) -> None:
    owner = create_organisation(engine, "Owner")
    run_id = create_run(engine, owner)
    record_permission(Database(None, engine), run_id, owner, permission("b.example", "excluded"))
    stranger = create_user(engine, organisation_id=create_organisation(engine, "Other"))
    token = create_session(engine, stranger.id)

    response = send_with_session(client, "GET", f"/runs/{run_id}", token)

    assert response.status_code == 404 and "b.example" not in response.text
    assert response.json()["detail"] == NOT_FOUND
    assert send_with_session(client, "GET", "/runs", token).json() == {"items": []}


def test_a_run_without_exclusion_lists_none(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = create_run(engine, user.organisation_id)
    body = send_with_session(client, "GET", f"/runs/{run_id}", token).json()
    assert body["excluded_sources"] == []
    assert uuid.UUID(body["id"]) == run_id


def test_the_database_suppression_list_matches_active_domain_entries_and_subdomains(
    engine: Engine,
) -> None:
    with Session(engine) as db:
        db.add_all(
            [
                SuppressionEntry(kind="domain", value="blocked.example"),
                SuppressionEntry(
                    kind="domain", value="removed.example", removed_at=utc_now() - timedelta(days=1)
                ),
                SuppressionEntry(kind="person_name", value="other.example"),
            ]
        )
        db.commit()
    suppression = DatabaseSuppressionList(Database(None, engine))

    assert suppression.is_suppressed("blocked.example")
    assert suppression.is_suppressed("www.Blocked.example.")
    assert not suppression.is_suppressed("notblocked.example")
    assert not suppression.is_suppressed("removed.example")
    assert not suppression.is_suppressed("other.example")  # a person's name is not a domain
