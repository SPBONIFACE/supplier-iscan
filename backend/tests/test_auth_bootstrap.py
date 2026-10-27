"""First start: the local administrator and the default organisation (issue #8, criterion 5)."""

import dataclasses
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.auth.bootstrap import DEFAULT_ORGANISATION_NAME, ensure_local_administrator
from app.auth.passwords import verify_password
from app.config import ConfigurationError, Settings
from app.main import create_app
from app.models import Organisation, User
from tests.support import BASE_URL

ADMIN_EMAIL = "Admin@Example.TEST"
ADMIN_PASSWORD = "Sentinel-Admin-Pa55-1f9d"  # noqa: S105 - test credential


@pytest.fixture
def admin_settings(settings: Settings) -> Settings:
    return dataclasses.replace(settings, admin_email=ADMIN_EMAIL, admin_password=ADMIN_PASSWORD)


def counts(engine: Engine) -> tuple[int, int]:
    with Session(engine) as db:
        users = db.scalar(select(func.count()).select_from(User))
        organisations = db.scalar(select(func.count()).select_from(Organisation))
    return users or 0, organisations or 0


def test_first_start_creates_one_administrator_in_an_active_default_organisation(
    engine: Engine, admin_settings: Settings
) -> None:
    with Session(engine) as db:
        assert ensure_local_administrator(db, admin_settings) is True

    with Session(engine) as db:
        admin = db.execute(select(User)).scalar_one()
        organisation = db.execute(select(Organisation)).scalar_one()
    assert admin.role == "admin"
    assert admin.email == "admin@example.test"
    assert admin.organisation_id == organisation.id
    assert organisation.name == DEFAULT_ORGANISATION_NAME
    assert organisation.status == "active"
    assert admin.password_hash.startswith("$argon2id$")
    assert verify_password(admin.password_hash, ADMIN_PASSWORD)
    assert ADMIN_PASSWORD not in admin.password_hash


def test_restart_creates_nothing_and_keeps_the_password(
    engine: Engine, admin_settings: Settings
) -> None:
    with Session(engine) as db:
        ensure_local_administrator(db, admin_settings)
    with Session(engine) as db:
        first_hash = db.scalar(select(User.password_hash))

    changed = dataclasses.replace(admin_settings, admin_password="a different password")
    with Session(engine) as db:
        assert ensure_local_administrator(db, changed) is False

    assert counts(engine) == (1, 1)
    with Session(engine) as db:
        assert db.scalar(select(User.password_hash)) == first_hash


@pytest.mark.parametrize(
    ("email", "password", "named", "not_named"),
    [
        (None, ADMIN_PASSWORD, ["ADMIN_EMAIL"], ["ADMIN_PASSWORD"]),
        (ADMIN_EMAIL, None, ["ADMIN_PASSWORD"], ["ADMIN_EMAIL"]),
        (None, None, ["ADMIN_EMAIL", "ADMIN_PASSWORD"], []),
    ],
)
def test_missing_setting_stops_with_its_name_and_never_a_value(
    engine: Engine,
    settings: Settings,
    email: str | None,
    password: str | None,
    named: list[str],
    not_named: list[str],
) -> None:
    incomplete = dataclasses.replace(settings, admin_email=email, admin_password=password)

    with Session(engine) as db, pytest.raises(ConfigurationError) as raised:
        ensure_local_administrator(db, incomplete)

    message = str(raised.value)
    for name in named:
        assert name in message
    for name in not_named:
        assert name not in message
    assert ADMIN_PASSWORD not in message
    assert ADMIN_EMAIL.lower() not in message.lower()
    assert counts(engine) == (0, 0)


def test_startup_creates_the_administrator_who_can_then_log_in(
    engine: Engine, admin_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    with TestClient(create_app(admin_settings, engine=engine), base_url=BASE_URL) as client:
        login = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        me = client.get("/auth/me")

    assert login.status_code == 200
    assert me.json()["role"] == "admin"
    with Session(engine) as db:
        assert me.json()["organisation_id"] == str(db.scalar(select(Organisation.id)))
    assert "Local administrator created" in caplog.text
    assert ADMIN_PASSWORD not in caplog.text


def test_second_startup_creates_no_second_administrator(
    engine: Engine, admin_settings: Settings
) -> None:
    with TestClient(create_app(admin_settings, engine=engine)):
        pass
    with TestClient(create_app(admin_settings, engine=engine)):
        pass

    assert counts(engine) == (1, 1)


def test_startup_stops_when_a_setting_is_missing(
    engine: Engine, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    incomplete = dataclasses.replace(settings, admin_email=ADMIN_EMAIL, admin_password=None)

    with pytest.raises(ConfigurationError, match="ADMIN_PASSWORD"):
        with TestClient(create_app(incomplete, engine=engine)):
            pass  # pragma: no cover - startup fails before this line

    assert "Startup stopped" in caplog.text
    assert "ADMIN_PASSWORD" in caplog.text
    assert counts(engine) == (0, 0)


def test_settings_are_not_needed_once_a_user_exists(
    engine: Engine, admin_settings: Settings, settings: Settings
) -> None:
    with Session(engine) as db:
        ensure_local_administrator(db, admin_settings)

    # A restart without the settings (they may be removed after first start) is fine.
    with TestClient(create_app(settings, engine=engine)):
        pass

    assert counts(engine) == (1, 1)
