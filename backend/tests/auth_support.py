"""Shared check for protected endpoints. Every issue that adds a protected endpoint calls it:

    def test_list_things_requires_a_session(client: TestClient, engine: Engine) -> None:
        assert_requires_session(client, engine, "GET", "/things")

It sends the request with no session cookie, a tampered one, an unknown one, an expired one and a
revoked (logged-out) one, and expects 401 with the generic message each time. It then sends it
with a valid session and expects anything but 401, so that the check cannot pass by accident.
"""

from datetime import timedelta
from typing import Any

import httpx2
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.auth.dependencies import AUTHENTICATION_REQUIRED
from app.auth.sessions import SESSION_COOKIE_NAME, new_token
from app.db import utc_now
from tests.factories import TestUser, create_session, create_user


def send_with_session(
    client: TestClient, method: str, path: str, token: str | None, **kwargs: Any
) -> httpx2.Response:
    """Send one request with exactly this session cookie (or none), ignoring the cookie jar."""
    client.cookies.clear()
    headers = dict(kwargs.pop("headers", None) or {})
    if token is not None:
        headers["Cookie"] = f"{SESSION_COOKIE_NAME}={token}"
    return client.request(method, path, headers=headers, **kwargs)


def tamper(token: str) -> str:
    last = "A" if token[-1] != "A" else "B"
    return token[:-1] + last


def assert_requires_session(
    client: TestClient,
    engine: Engine,
    method: str,
    path: str,
    user: TestUser | None = None,
    **kwargs: Any,
) -> None:
    user = user or create_user(engine)
    now = utc_now()
    cases: dict[str, str | None] = {
        "missing": None,
        "empty": "",
        "tampered": tamper(create_session(engine, user.id)),
        "unknown": new_token(),
        "expired": create_session(engine, user.id, expires_at=now - timedelta(seconds=1)),
        "revoked": create_session(engine, user.id, revoked_at=now),
    }
    for case, token in cases.items():
        response = send_with_session(client, method, path, token, **kwargs)
        assert response.status_code == 401, (
            f"{method} {path}, {case} session: {response.status_code}"
        )
        assert response.json() == {"detail": AUTHENTICATION_REQUIRED}, f"{case} session"

    valid = send_with_session(client, method, path, create_session(engine, user.id), **kwargs)
    assert valid.status_code != 401, f"{method} {path} refuses a valid session"
