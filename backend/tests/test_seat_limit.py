"""Seat limit on acceptance, including simultaneous acceptances (issue #9, criterion 4)."""

import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import httpx2
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.config import Settings
from app.db import utc_now
from app.invitations.service import INVALID_INVITATION, SEAT_LIMIT_REACHED
from app.models import Invitation, User
from tests.factories import create_invitation, create_organisation, create_user
from tests.support import make_client

PASSWORD = "a long enough password for any test setting"
# Test values only: the seat limit is whatever the administrator enters.
SEATS = 3
CONCURRENT = 6


def accept(client: TestClient, token: str) -> httpx2.Response:
    return client.post(f"/invitations/{token}/accept", json={"password": PASSWORD})


def member_count(engine: Engine, organisation_id: uuid.UUID) -> int:
    with Session(engine) as db:
        return (
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.organisation_id == organisation_id)
            )
            or 0
        )


def fill(engine: Engine, organisation_id: uuid.UUID, count: int) -> None:
    for _ in range(count):
        create_user(engine, organisation_id=organisation_id)


def test_acceptance_is_refused_when_every_seat_is_taken(client: TestClient, engine: Engine) -> None:
    organisation_id = create_organisation(engine, seat_limit=SEATS)
    fill(engine, organisation_id, SEATS)
    invitation = create_invitation(engine, organisation_id)

    response = accept(client, invitation.token)

    assert response.status_code == 409
    assert response.json() == {"detail": SEAT_LIMIT_REACHED}
    assert "set-cookie" not in response.headers
    assert member_count(engine, organisation_id) == SEATS
    with Session(engine) as db:
        # Not consumed: it works once a seat is free (or the limit is raised).
        assert db.get_one(Invitation, invitation.id).used_at is None


def test_the_last_seat_can_be_taken(client: TestClient, engine: Engine) -> None:
    organisation_id = create_organisation(engine, seat_limit=SEATS)
    fill(engine, organisation_id, SEATS - 1)

    response = accept(client, create_invitation(engine, organisation_id).token)

    assert response.status_code == 200
    assert member_count(engine, organisation_id) == SEATS


def test_every_role_counts_against_the_seat_limit(client: TestClient, engine: Engine) -> None:
    organisation_id = create_organisation(engine, seat_limit=1)
    create_user(engine, role="admin", organisation_id=organisation_id)

    response = accept(client, create_invitation(engine, organisation_id).token)

    assert response.status_code == 409


def test_without_a_seat_limit_there_is_no_limit(client: TestClient, engine: Engine) -> None:
    organisation_id = create_organisation(engine, seat_limit=None)
    fill(engine, organisation_id, SEATS * 2)

    response = accept(client, create_invitation(engine, organisation_id).token)

    assert response.status_code == 200


def test_another_organisation_s_members_do_not_count(client: TestClient, engine: Engine) -> None:
    full = create_organisation(engine, seat_limit=1)
    fill(engine, full, 1)
    organisation_id = create_organisation(engine, seat_limit=1)

    assert accept(client, create_invitation(engine, organisation_id).token).status_code == 200


def test_an_invalid_link_is_refused_before_the_seat_limit_is_considered(
    client: TestClient, engine: Engine
) -> None:
    # A full organisation must not turn an unusable link into a "seat limit" answer.
    organisation_id = create_organisation(engine, seat_limit=1)
    fill(engine, organisation_id, 1)
    revoked = create_invitation(engine, organisation_id, revoked_at=utc_now())

    response = accept(client, revoked.token)

    assert response.status_code == 404
    assert response.json() == {"detail": INVALID_INVITATION}


def _accept_together(
    engine: Engine, settings: Settings, tokens: list[str]
) -> list[httpx2.Response]:
    """Send one acceptance per token, all released at the same moment, each from its own thread
    and client (on one application, warmed up so that its routes are built before the race)."""
    first = make_client(settings=settings, engine=engine)
    assert accept(first, "warm-up").status_code == 404
    clients = [
        TestClient(first.app, base_url=str(first.base_url), raise_server_exceptions=False)
        for _ in tokens
    ]
    barrier = threading.Barrier(len(tokens))

    def run(index: int) -> httpx2.Response:
        barrier.wait()
        return accept(clients[index], tokens[index])

    with ThreadPoolExecutor(max_workers=len(tokens)) as pool:
        return list(pool.map(run, range(len(tokens))))


def test_simultaneous_acceptances_for_the_last_seat_let_exactly_one_in(
    engine: Engine, settings: Settings
) -> None:
    organisation_id = create_organisation(engine, seat_limit=SEATS)
    fill(engine, organisation_id, SEATS - 1)
    tokens = [create_invitation(engine, organisation_id).token for _ in range(CONCURRENT)]

    responses = _accept_together(engine, settings, tokens)

    assert Counter(r.status_code for r in responses) == {200: 1, 409: CONCURRENT - 1}
    assert all(
        r.json() == {"detail": SEAT_LIMIT_REACHED} for r in responses if r.status_code == 409
    )
    assert member_count(engine, organisation_id) == SEATS
    with Session(engine) as db:
        assert db.scalar(select(func.count()).where(Invitation.used_at.is_not(None))) == 1


def test_simultaneous_acceptances_of_one_link_let_exactly_one_in(
    engine: Engine, settings: Settings
) -> None:
    organisation_id = create_organisation(engine)
    token = create_invitation(engine, organisation_id).token

    responses = _accept_together(engine, settings, [token] * CONCURRENT)

    assert Counter(r.status_code for r in responses) == {200: 1, 404: CONCURRENT - 1}
    assert member_count(engine, organisation_id) == 1


def test_an_acceptance_waits_for_a_concurrent_one_and_then_counts_again(
    client: TestClient, engine: Engine
) -> None:
    # Deterministic version of the race: another transaction holds the organisation row (as a
    # concurrent acceptance does) and takes the last seat while this acceptance waits.
    organisation_id = create_organisation(engine, seat_limit=SEATS)
    fill(engine, organisation_id, SEATS - 1)
    invitation = create_invitation(engine, organisation_id)

    with engine.connect() as other:
        other.execute(
            text("SELECT id FROM organisations WHERE id = :id FOR UPDATE"), {"id": organisation_id}
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(accept, client, invitation.token)
            time.sleep(1.0)
            assert not pending.done(), "the acceptance did not wait for the organisation lock"
            other.execute(
                text(
                    "INSERT INTO users (id, organisation_id, email, password_hash, role) "
                    "VALUES (:id, :organisation_id, :email, :hash, 'member')"
                ),
                {
                    "id": uuid.uuid4(),
                    "organisation_id": organisation_id,
                    "email": "racer@example.test",
                    "hash": hash_password("racer"),
                },
            )
            other.commit()
            response = pending.result(timeout=30)

    assert response.status_code == 409
    assert response.json() == {"detail": SEAT_LIMIT_REACHED}
    assert member_count(engine, organisation_id) == SEATS
