"""POST /auth/logout, GET /auth/me, and 401 on protected endpoints (issue #8, criteria 3-4)."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.auth.dependencies import AUTHENTICATION_REQUIRED
from app.auth.sessions import SESSION_COOKIE_NAME
from app.db import utc_now
from app.errors import SERVICE_UNAVAILABLE
from app.models import UserSession
from tests.auth_support import assert_requires_session, send_with_session
from tests.factories import TestUser, create_session, create_user
from tests.support import UNREACHABLE_DATABASE_URL, make_client


def log_in(client: TestClient, user: TestUser) -> str:
    response = client.post("/auth/login", json={"email": user.email, "password": user.password})
    assert response.status_code == 200
    token = client.cookies.get(SESSION_COOKIE_NAME)
    assert token
    return token


def test_me_returns_the_current_user(client: TestClient, engine: Engine) -> None:
    user = create_user(engine, role="admin")
    log_in(client, user)

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "email": user.email,
        "role": "admin",
        "organisation_id": str(user.organisation_id),
    }


def test_logout_invalidates_the_session_on_the_server(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    token = log_in(client, user)

    response = client.post("/auth/logout")

    assert response.status_code == 204
    assert response.content == b""
    with Session(engine) as db:
        assert db.scalar(select(UserSession.revoked_at)) is not None
    # Replaying the old cookie is refused.
    replay = send_with_session(client, "GET", "/auth/me", token)
    assert replay.status_code == 401
    assert replay.json() == {"detail": AUTHENTICATION_REQUIRED}
    assert send_with_session(client, "POST", "/auth/logout", token).status_code == 401


def test_logout_clears_the_cookie(client: TestClient, engine: Engine) -> None:
    log_in(client, create_user(engine))

    response = client.post("/auth/logout")

    set_cookie = response.headers["set-cookie"].lower()
    assert set_cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "max-age=0" in set_cookie
    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "samesite=lax" in set_cookie


def test_logout_ends_only_the_current_session(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    other = create_session(engine, user.id)
    log_in(client, user)

    client.post("/auth/logout")

    assert send_with_session(client, "GET", "/auth/me", other).status_code == 200


def test_session_expires(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    token = log_in(client, user)
    with Session(engine) as db:
        db.execute(update(UserSession).values(expires_at=utc_now() - timedelta(seconds=1)))
        db.commit()

    assert send_with_session(client, "GET", "/auth/me", token).status_code == 401


def test_me_requires_a_session(client: TestClient, engine: Engine) -> None:
    assert_requires_session(client, engine, "GET", "/auth/me")


def test_logout_requires_a_session(client: TestClient, engine: Engine) -> None:
    assert_requires_session(client, engine, "POST", "/auth/logout")


def test_missing_session_is_refused_before_any_database_access() -> None:
    response = make_client(database_url=UNREACHABLE_DATABASE_URL).get("/auth/me")

    assert response.status_code == 401


def test_session_check_returns_503_when_the_database_is_unreachable() -> None:
    response = send_with_session(
        make_client(database_url=UNREACHABLE_DATABASE_URL), "GET", "/auth/me", "some-token"
    )

    assert response.status_code == 503
    assert response.json() == {"detail": SERVICE_UNAVAILABLE}


def test_an_oversized_cookie_is_refused(client: TestClient, engine: Engine) -> None:
    response = send_with_session(client, "GET", "/auth/me", "x" * 4000)

    assert response.status_code == 401
