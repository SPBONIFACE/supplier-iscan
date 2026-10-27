"""POST /auth/login: cookie, argon2 storage, generic 401, 422, 503 (issue #8, criteria 1-2)."""

from http.cookies import SimpleCookie

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.auth.passwords import verify_password
from app.auth.routes import INVALID_CREDENTIALS
from app.auth.sessions import SESSION_COOKIE_NAME, SESSION_LIFETIME, hash_token
from app.errors import SERVICE_UNAVAILABLE
from app.models import User, UserSession
from tests.factories import create_user
from tests.support import UNREACHABLE_DATABASE_URL, make_client


def session_cookie(set_cookie: str) -> tuple[str, dict[str, str]]:
    """The session token and the attributes of a Set-Cookie header (attribute names lower-cased)."""
    morsel = SimpleCookie(set_cookie)[SESSION_COOKIE_NAME]
    raw = set_cookie.lower()
    flags = {name: str(morsel[name]).lower() for name in ("samesite", "path", "max-age")}
    flags["httponly"] = "yes" if "httponly" in raw else ""
    flags["secure"] = "yes" if "; secure" in raw else ""
    return morsel.value, flags


def test_valid_login_returns_200_and_a_secure_session_cookie(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)

    response = client.post("/auth/login", json={"email": user.email, "password": user.password})

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "email": user.email,
        "role": "member",
        "organisation_id": str(user.organisation_id),
    }
    token, flags = session_cookie(response.headers["set-cookie"])
    assert token
    assert flags["httponly"] == "yes"
    assert flags["secure"] == "yes"
    assert flags["samesite"] == "lax"
    assert flags["path"] == "/"
    assert flags["max-age"] == str(int(SESSION_LIFETIME.total_seconds()))


def test_login_stores_only_a_hash_of_the_session_token(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)

    response = client.post("/auth/login", json={"email": user.email, "password": user.password})
    token, _ = session_cookie(response.headers["set-cookie"])

    with Session(engine) as db:
        stored = db.scalars(select(UserSession.token_hash)).all()
    assert stored == [hash_token(token)]
    assert token not in stored


def test_password_is_stored_only_as_an_argon2id_hash(engine: Engine) -> None:
    user = create_user(engine, password="plain-text-never-stored")

    with Session(engine) as db:
        row = db.execute(select(User).where(User.id == user.id)).scalar_one()
        columns = {column.key: getattr(row, column.key) for column in User.__table__.columns}

    assert row.password_hash.startswith("$argon2id$")
    assert verify_password(row.password_hash, "plain-text-never-stored")
    assert all("plain-text-never-stored" not in str(value) for value in columns.values())


def test_email_is_matched_without_case_or_surrounding_spaces(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine, email="buyer@example.test")

    response = client.post(
        "/auth/login", json={"email": "  Buyer@Example.TEST ", "password": user.password}
    )

    assert response.status_code == 200


def test_login_records_the_login_time(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)

    client.post("/auth/login", json={"email": user.email, "password": user.password})

    with Session(engine) as db:
        assert db.scalar(select(User.last_login_at).where(User.id == user.id)) is not None


def test_wrong_password_and_unknown_email_get_the_same_401(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)

    wrong_password = client.post(
        "/auth/login", json={"email": user.email, "password": "not the password"}
    )
    unknown_email = client.post(
        "/auth/login", json={"email": "nobody@example.test", "password": user.password}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() == {"detail": INVALID_CREDENTIALS}
    assert "set-cookie" not in wrong_password.headers
    assert "set-cookie" not in unknown_email.headers


@pytest.mark.parametrize(
    ("body", "field", "message"),
    [
        ({"email": "", "password": "secret"}, "email", "Email is required."),
        ({"email": "   ", "password": "secret"}, "email", "Email is required."),
        ({"email": "a@example.test", "password": ""}, "password", "Password is required."),
        ({"password": "secret"}, "email", "Email is required."),
        ({"email": "a@example.test"}, "password", "Password is required."),
        ({"email": "a@example.test", "password": "x" * 1025}, "password", "Password is too long."),
        ({"email": "a" * 321, "password": "secret"}, "email", "Email is too long."),
    ],
)
def test_invalid_login_body_returns_422_with_a_clear_message(
    body: dict[str, str], field: str, message: str
) -> None:
    # Validation happens before any database access: the database being down does not matter.
    response = make_client(database_url=UNREACHABLE_DATABASE_URL).post("/auth/login", json=body)

    assert response.status_code == 422
    assert response.json() == {
        "detail": "The request is not valid.",
        "errors": [{"field": field, "message": message}],
    }


def test_empty_email_and_password_are_both_reported() -> None:
    response = make_client(database_url=UNREACHABLE_DATABASE_URL).post(
        "/auth/login", json={"email": "", "password": ""}
    )

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {"field": "email", "message": "Email is required."},
        {"field": "password", "message": "Password is required."},
    ]


@pytest.mark.parametrize("content", ["not json", "[]", '"text"'])
def test_login_body_that_is_not_a_json_object_returns_422(content: str) -> None:
    response = make_client(database_url=UNREACHABLE_DATABASE_URL).post(
        "/auth/login", content=content, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {"field": "body", "message": "The request body must be a JSON object."}
    ]


@pytest.mark.parametrize(
    "database_url", [UNREACHABLE_DATABASE_URL, None, "not a connection string"]
)
def test_login_returns_503_with_a_plain_message_when_the_database_is_unavailable(
    database_url: str | None,
) -> None:
    response = make_client(database_url=database_url).post(
        "/auth/login", json={"email": "a@example.test", "password": "secret"}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": SERVICE_UNAVAILABLE}
    assert "Traceback" not in response.text
    assert "127.0.0.1" not in response.text
    assert "nothing" not in response.text  # the password of UNREACHABLE_DATABASE_URL
