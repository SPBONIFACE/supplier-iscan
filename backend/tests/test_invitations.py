"""Invitations: creation, validity check, acceptance, revocation (issue #9, criteria 2, 3, 5)."""

import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.auth.passwords import verify_password
from app.auth.sessions import SESSION_COOKIE_NAME, SESSION_LIFETIME, hash_token
from app.config import Settings
from app.db import utc_now
from app.errors import NOT_FOUND
from app.invitations.service import (
    ALREADY_USED,
    EMAIL_HAS_ACCOUNT,
    INVALID_INVITATION,
)
from app.models import Invitation, UsageEvent, User
from tests.admin_support import sign_in
from tests.auth_support import send_with_session
from tests.factories import TestInvitation, create_invitation, create_organisation, create_user
from tests.support import make_client

# Test values only: the delay and the minimum length are configuration.
VALIDITY = timedelta(hours=5)
MIN_LENGTH = 15
GOOD_PASSWORD = "p" * MIN_LENGTH


@pytest.fixture
def configured(settings: Settings) -> Settings:
    return replace(settings, invitation_validity=VALIDITY, password_min_length=MIN_LENGTH)


@pytest.fixture
def app_client(engine: Engine, configured: Settings) -> Iterator[TestClient]:
    yield make_client(settings=configured, engine=engine)


def accept(client: TestClient, token: str, password: str = GOOD_PASSWORD) -> httpx2.Response:
    client.cookies.clear()
    return client.post(f"/invitations/{token}/accept", json={"password": password})


# --- create ---------------------------------------------------------------------------------


def test_administrator_creates_an_invitation_and_gets_the_link(
    app_client: TestClient, engine: Engine
) -> None:
    sign_in(app_client, engine, role="admin")
    organisation_id = create_organisation(engine, name="Invitee Org")
    before = utc_now()

    response = app_client.post(
        f"/admin/organisations/{organisation_id}/invitations",
        json={"email": "  New.Person@Example.TEST "},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new.person@example.test"
    assert body["organisation_id"] == str(organisation_id)
    prefix = "http://localhost:5173/invitations/"
    assert body["link"].startswith(prefix)
    token = body["link"].removeprefix(prefix)
    assert len(token) >= 43

    with Session(engine) as db:
        stored = db.get_one(Invitation, uuid.UUID(body["id"]))
        # Only the hash of the token is stored, in no column the token itself.
        assert stored.token_hash == hash_token(token)
        row = db.execute(select(Invitation.__table__)).one()
        assert all(token not in str(value) for value in row)
        # Expires after the configured delay.
        assert before + VALIDITY <= stored.expires_at <= utc_now() + VALIDITY
        assert stored.expires_at - stored.created_at == VALIDITY
        assert stored.used_at is None and stored.revoked_at is None


def test_the_delay_comes_from_configuration(engine: Engine, configured: Settings) -> None:
    other_delay = VALIDITY * 3
    client = make_client(
        settings=replace(configured, invitation_validity=other_delay), engine=engine
    )
    sign_in(client, engine, role="admin")
    organisation_id = create_organisation(engine)

    response = client.post(
        f"/admin/organisations/{organisation_id}/invitations", json={"email": "a@example.test"}
    )

    with Session(engine) as db:
        stored = db.get_one(Invitation, uuid.UUID(response.json()["id"]))
        assert stored.expires_at - stored.created_at == other_delay


def test_inviting_an_email_that_has_an_account_answers_409(
    app_client: TestClient, engine: Engine
) -> None:
    sign_in(app_client, engine, role="admin")
    existing = create_user(engine, email="taken@example.test")

    response = app_client.post(
        f"/admin/organisations/{existing.organisation_id}/invitations",
        json={"email": "TAKEN@example.test"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": EMAIL_HAS_ACCOUNT}
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Invitation)) == 0


@pytest.mark.parametrize("email", ["", "  ", "no-at-sign", "a@b", "two@@example.test", "x" * 321])
def test_an_invalid_email_answers_422(app_client: TestClient, engine: Engine, email: str) -> None:
    sign_in(app_client, engine, role="admin")
    organisation_id = create_organisation(engine)

    response = app_client.post(
        f"/admin/organisations/{organisation_id}/invitations", json={"email": email}
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "email"


@pytest.mark.parametrize("organisation_id", [str(uuid.uuid4()), "nope"])
def test_inviting_into_an_unknown_organisation_answers_404(
    app_client: TestClient, engine: Engine, organisation_id: str
) -> None:
    sign_in(app_client, engine, role="admin")

    response = app_client.post(
        f"/admin/organisations/{organisation_id}/invitations", json={"email": "a@example.test"}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": NOT_FOUND}


# --- check and accept -----------------------------------------------------------------------


def test_a_valid_link_can_be_checked(app_client: TestClient, engine: Engine) -> None:
    organisation_id = create_organisation(engine, name="Checked Org")
    invitation = create_invitation(engine, organisation_id, email="check@example.test")

    response = app_client.get(f"/invitations/{invitation.token}")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "check@example.test"
    assert body["organisation_name"] == "Checked Org"


def test_accepting_creates_a_member_and_signs_them_in(
    app_client: TestClient, engine: Engine
) -> None:
    organisation_id = create_organisation(engine)
    invitation = create_invitation(engine, organisation_id, email="joiner@example.test")

    response = accept(app_client, invitation.token)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "joiner@example.test"
    assert body["role"] == "member"
    assert body["organisation_id"] == str(organisation_id)

    # Signed in directly: the cookie is set exactly as on login.
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    lowered = set_cookie.lower()
    for flag in ("httponly", "secure", "samesite=lax", "path=/"):
        assert flag in lowered
    assert f"max-age={int(SESSION_LIFETIME.total_seconds())}" in lowered
    me = app_client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == body["id"]

    with Session(engine) as db:
        user = db.get_one(User, uuid.UUID(body["id"]))
        assert user.role == "member"
        assert user.organisation_id == organisation_id
        assert user.password_hash.startswith("$argon2id$")
        assert GOOD_PASSWORD not in user.password_hash
        assert verify_password(user.password_hash, GOOD_PASSWORD)
        stored = db.get_one(Invitation, invitation.id)
        assert stored.used_at is not None
        events = db.scalars(select(UsageEvent)).all()
        assert [(e.kind, e.user_id, e.organisation_id) for e in events] == [
            ("login", user.id, organisation_id)
        ]


def test_the_new_member_can_log_in_with_the_password(
    app_client: TestClient, engine: Engine
) -> None:
    invitation = create_invitation(engine, create_organisation(engine))
    accept(app_client, invitation.token)
    app_client.cookies.clear()

    response = app_client.post(
        "/auth/login", json={"email": invitation.email, "password": GOOD_PASSWORD}
    )

    assert response.status_code == 200


def _refused_tokens(engine: Engine) -> dict[str, str]:
    organisation_id = create_organisation(engine)
    now = utc_now()
    valid = create_invitation(engine, organisation_id).token
    return {
        "used": create_invitation(engine, organisation_id, used_at=now).token,
        "expired": create_invitation(
            engine, organisation_id, expires_at=now - timedelta(seconds=1)
        ).token,
        "revoked": create_invitation(engine, organisation_id, revoked_at=now).token,
        "unknown": "x" * 43,
        "tampered": valid[:-1] + ("A" if valid[-1] != "A" else "B"),
        "oversized": "y" * 4000,
        "email has an account": create_invitation(
            engine, organisation_id, email=create_user(engine).email
        ).token,
    }


def test_unusable_links_are_refused_with_the_same_answer(
    app_client: TestClient, engine: Engine
) -> None:
    answers = {}
    for case, token in _refused_tokens(engine).items():
        check = app_client.get(f"/invitations/{token}")
        accepted = accept(app_client, token)
        assert check.status_code == 404, case
        assert accepted.status_code == 404, case
        assert "set-cookie" not in accepted.headers, case
        answers[case] = (check.json(), accepted.json())

    # The same message in every case: it says nothing about any account.
    assert set(map(str, answers.values())) == {
        str(({"detail": INVALID_INVITATION}, {"detail": INVALID_INVITATION}))
    }
    with Session(engine) as db:
        # Only the user created for the "email has an account" case.
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_a_link_works_only_once(app_client: TestClient, engine: Engine) -> None:
    invitation = create_invitation(engine, create_organisation(engine))

    first = accept(app_client, invitation.token)
    second = accept(app_client, invitation.token, password="q" * MIN_LENGTH)

    assert first.status_code == 200
    assert second.status_code == 404
    assert second.json() == {"detail": INVALID_INVITATION}
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_a_link_that_expired_after_it_was_checked_is_refused(
    app_client: TestClient, engine: Engine
) -> None:
    invitation = create_invitation(engine, create_organisation(engine))
    assert app_client.get(f"/invitations/{invitation.token}").status_code == 200
    with Session(engine) as db:
        db.get_one(Invitation, invitation.id).expires_at = utc_now() - timedelta(seconds=1)
        db.commit()

    assert accept(app_client, invitation.token).status_code == 404


def test_a_password_shorter_than_the_minimum_answers_422(
    app_client: TestClient, engine: Engine
) -> None:
    invitation = create_invitation(engine, create_organisation(engine))

    response = accept(app_client, invitation.token, password="s" * (MIN_LENGTH - 1))

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {"field": "password", "message": f"Password must be at least {MIN_LENGTH} characters."}
    ]
    assert "s" * (MIN_LENGTH - 1) not in response.text
    # The invitation is still usable.
    assert accept(app_client, invitation.token).status_code == 200


def test_the_minimum_length_comes_from_configuration(engine: Engine, configured: Settings) -> None:
    client = make_client(
        settings=replace(configured, password_min_length=MIN_LENGTH + 5), engine=engine
    )
    invitation = create_invitation(engine, create_organisation(engine))

    assert accept(client, invitation.token, password="p" * (MIN_LENGTH + 4)).status_code == 422
    assert accept(client, invitation.token, password="p" * (MIN_LENGTH + 5)).status_code == 200


@pytest.mark.parametrize("body", [{}, {"password": ""}, {"password": "p" * 1025}, []])
def test_a_missing_or_malformed_password_answers_422(
    app_client: TestClient, engine: Engine, body: object
) -> None:
    invitation = create_invitation(engine, create_organisation(engine))

    response = app_client.post(f"/invitations/{invitation.token}/accept", json=body)

    assert response.status_code == 422


def test_accepting_needs_no_session(app_client: TestClient, engine: Engine) -> None:
    invitation = create_invitation(engine, create_organisation(engine))

    response = send_with_session(
        app_client,
        "POST",
        f"/invitations/{invitation.token}/accept",
        None,
        json={"password": GOOD_PASSWORD},
    )

    assert response.status_code == 200


# --- revoke ---------------------------------------------------------------------------------


def test_a_revoked_invitation_cannot_be_accepted(app_client: TestClient, engine: Engine) -> None:
    invitation = create_invitation(engine, create_organisation(engine))
    sign_in(app_client, engine, role="admin")

    revoked = app_client.delete(f"/admin/invitations/{invitation.id}")

    assert revoked.status_code == 204
    assert revoked.content == b""
    with Session(engine) as db:
        assert db.get_one(Invitation, invitation.id).revoked_at is not None
    assert app_client.get(f"/invitations/{invitation.token}").status_code == 404
    refused = accept(app_client, invitation.token)
    assert refused.status_code == 404
    assert refused.json() == {"detail": INVALID_INVITATION}


def test_revoking_twice_changes_nothing(app_client: TestClient, engine: Engine) -> None:
    invitation = create_invitation(engine, create_organisation(engine))
    sign_in(app_client, engine, role="admin")
    app_client.delete(f"/admin/invitations/{invitation.id}")
    with Session(engine) as db:
        first = db.get_one(Invitation, invitation.id).revoked_at

    again = app_client.delete(f"/admin/invitations/{invitation.id}")

    assert again.status_code == 204
    with Session(engine) as db:
        assert db.get_one(Invitation, invitation.id).revoked_at == first


def test_a_used_invitation_cannot_be_revoked(app_client: TestClient, engine: Engine) -> None:
    invitation = create_invitation(engine, create_organisation(engine))
    accept(app_client, invitation.token)
    sign_in(app_client, engine, role="admin")

    response = app_client.delete(f"/admin/invitations/{invitation.id}")

    assert response.status_code == 409
    assert response.json() == {"detail": ALREADY_USED}
    with Session(engine) as db:
        assert db.get_one(Invitation, invitation.id).revoked_at is None


@pytest.mark.parametrize("invitation_id", [str(uuid.uuid4()), "123"])
def test_revoking_an_unknown_invitation_answers_404(
    app_client: TestClient, engine: Engine, invitation_id: str
) -> None:
    sign_in(app_client, engine, role="admin")

    response = app_client.delete(f"/admin/invitations/{invitation_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": NOT_FOUND}


def test_a_member_cannot_revoke_an_invitation(app_client: TestClient, engine: Engine) -> None:
    organisation_id = create_organisation(engine)
    invitation: TestInvitation = create_invitation(engine, organisation_id)
    sign_in(app_client, engine, role="member", organisation_id=organisation_id)

    response = app_client.delete(f"/admin/invitations/{invitation.id}")

    assert response.status_code == 403
    with Session(engine) as db:
        assert db.get_one(Invitation, invitation.id).revoked_at is None
