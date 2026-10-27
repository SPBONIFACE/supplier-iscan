"""Shared helpers for administrator-only endpoints.

    def test_thing_is_for_administrators(client: TestClient, engine: Engine) -> None:
        assert_requires_administrator(client, engine, "POST", "/admin/things", json={...})

It runs `assert_requires_session` (401 for every kind of missing or bad session), then checks that
a signed-in member gets 403 with the generic message, and that an administrator does not.
"""

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.auth.dependencies import ADMINISTRATOR_REQUIRED
from app.auth.sessions import SESSION_COOKIE_NAME
from tests.auth_support import assert_requires_session, send_with_session
from tests.factories import TestUser, create_session, create_user


def sign_in(
    client: TestClient,
    engine: Engine,
    role: str = "member",
    organisation_id: uuid.UUID | None = None,
) -> TestUser:
    """Create a user with this role and put a valid session cookie in the client's cookie jar."""
    user = create_user(engine, role=role, organisation_id=organisation_id)
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, create_session(engine, user.id))
    return user


def assert_requires_administrator(
    client: TestClient, engine: Engine, method: str, path: str, **kwargs: Any
) -> None:
    administrator = create_user(engine, role="admin")
    assert_requires_session(client, engine, method, path, user=administrator, **kwargs)

    member = create_user(engine, role="member")
    response = send_with_session(client, method, path, create_session(engine, member.id), **kwargs)
    assert response.status_code == 403, f"{method} {path} as a member: {response.status_code}"
    assert response.json() == {"detail": ADMINISTRATOR_REQUIRED}
