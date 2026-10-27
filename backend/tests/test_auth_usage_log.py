"""Usage log of logins, and no secret anywhere (issue #8, criterion 6)."""

import logging
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.auth.sessions import SESSION_COOKIE_NAME
from app.db import utc_now
from app.models import UsageEvent, User
from tests.factories import create_user

SENTINEL_PASSWORD = "Sentinel-Pa55word-8c41e7"  # noqa: S105 - test credential


def events(engine: Engine) -> list[UsageEvent]:
    with Session(engine) as db:
        return list(db.scalars(select(UsageEvent).order_by(UsageEvent.created_at)))


def assert_recent(event: UsageEvent) -> None:
    assert utc_now() - timedelta(minutes=1) < event.created_at <= utc_now()


def test_login_creates_a_login_event(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)

    client.post("/auth/login", json={"email": user.email, "password": user.password})

    [event] = events(engine)
    assert event.kind == "login"
    assert event.user_id == user.id
    assert event.organisation_id == user.organisation_id
    assert_recent(event)


def test_wrong_password_creates_a_login_failed_event_with_the_user(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)

    client.post("/auth/login", json={"email": user.email, "password": "wrong"})

    [event] = events(engine)
    assert event.kind == "login_failed"
    assert event.user_id == user.id
    assert event.organisation_id == user.organisation_id
    assert_recent(event)


def test_unknown_email_creates_a_login_failed_event_without_user(
    client: TestClient, engine: Engine
) -> None:
    client.post("/auth/login", json={"email": "nobody@example.test", "password": "whatever"})

    [event] = events(engine)
    assert event.kind == "login_failed"
    assert event.user_id is None
    assert event.organisation_id is None
    assert_recent(event)


def test_invalid_body_creates_no_event(client: TestClient, engine: Engine) -> None:
    client.post("/auth/login", json={"email": "", "password": ""})

    assert events(engine) == []


def test_no_password_hash_or_token_in_events_logs_or_error_responses(
    client: TestClient, engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    user = create_user(engine, password=SENTINEL_PASSWORD)
    error_bodies: list[str] = []

    def post(body: dict[str, Any]) -> None:
        response = client.post("/auth/login", json=body)
        if response.status_code >= 400:
            error_bodies.append(response.text)

    post({"email": user.email, "password": SENTINEL_PASSWORD + "-wrong"})
    post({"email": "nobody@example.test", "password": SENTINEL_PASSWORD})
    post({"email": user.email, "password": SENTINEL_PASSWORD + "x" * 1100})  # 422, too long
    post({"email": user.email, "password": SENTINEL_PASSWORD, "extra": SENTINEL_PASSWORD})
    post({"email": user.email, "password": SENTINEL_PASSWORD})
    token = client.cookies.get(SESSION_COOKIE_NAME)
    assert token
    me = client.get("/auth/me")
    logout = client.post("/auth/logout")
    replay = client.get("/auth/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"})
    error_bodies.append(replay.text)

    with Session(engine) as db:
        password_hash = db.scalar(select(User.password_hash).where(User.id == user.id))
        event_rows = [str(row) for row in db.execute(text("SELECT * FROM usage_events")).all()]
    assert password_hash
    assert len(event_rows) == 3  # two failed logins, one login (422s are not attempts)
    secrets = {"password": SENTINEL_PASSWORD, "hash": password_hash, "token": token}
    for name, secret in secrets.items():
        assert secret not in caplog.text, f"{name} in the logs"
        assert all(secret not in row for row in event_rows), f"{name} in a usage event"
        assert all(secret not in body for body in error_bodies), f"{name} in an error response"
        assert secret not in me.text, f"{name} in /auth/me"
        assert secret not in logout.text
