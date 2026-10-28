"""User records and invitations as seen by a member (issue #9, criterion 6; spec access rules)."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.errors import NOT_FOUND
from tests.admin_support import sign_in
from tests.auth_support import assert_requires_session
from tests.factories import create_invitation, create_organisation, create_user


def test_a_member_reads_their_own_record(client: TestClient, engine: Engine) -> None:
    member = sign_in(client, engine)

    response = client.get(f"/users/{member.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(member.id)
    assert body["email"] == member.email
    assert body["role"] == "member"
    assert body["organisation_id"] == str(member.organisation_id)
    assert body["last_login_at"] is None
    assert set(body) == {"id", "organisation_id", "email", "role", "created_at", "last_login_at"}


def test_a_member_cannot_read_other_users(client: TestClient, engine: Engine) -> None:
    member = sign_in(client, engine)
    colleague = create_user(engine, organisation_id=member.organisation_id)
    stranger = create_user(engine)
    administrator = create_user(engine, role="admin")

    answers = [
        client.get(f"/users/{other}")
        for other in (colleague.id, stranger.id, administrator.id, uuid.uuid4(), "not-a-uuid")
    ]

    # Another user, an unknown id and a malformed id: the same 404, so nothing leaks.
    assert [a.status_code for a in answers] == [404] * 5
    assert all(a.json() == {"detail": NOT_FOUND} for a in answers)
    assert len({a.content for a in answers}) == 1


def test_a_member_cannot_read_invitations(client: TestClient, engine: Engine) -> None:
    member = sign_in(client, engine)
    invitation = create_invitation(engine, member.organisation_id)

    # The only invitation read for anyone but an administrator is the link check, keyed by the
    # secret token: an invitation id (or anything else) answers 404.
    for path in (f"/invitations/{invitation.id}", f"/users/{invitation.id}"):
        response = client.get(path)
        assert response.status_code == 404, path

    # The administrator endpoints that reach invitations are closed to members (403).
    assert client.delete(f"/admin/invitations/{invitation.id}").status_code == 403
    assert (
        client.post(
            f"/admin/organisations/{member.organisation_id}/invitations",
            json={"email": "friend@example.test"},
        ).status_code
        == 403
    )


def test_an_administrator_reads_any_user(client: TestClient, engine: Engine) -> None:
    sign_in(client, engine, role="admin")
    other = create_user(engine, organisation_id=create_organisation(engine, name="Other"))

    response = client.get(f"/users/{other.id}")

    assert response.status_code == 200
    assert response.json()["email"] == other.email


def test_an_administrator_gets_404_for_an_unknown_user(client: TestClient, engine: Engine) -> None:
    sign_in(client, engine, role="admin")

    response = client.get(f"/users/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": NOT_FOUND}


def test_reading_a_user_requires_a_session(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)

    assert_requires_session(client, engine, "GET", f"/users/{user.id}", user=user)
