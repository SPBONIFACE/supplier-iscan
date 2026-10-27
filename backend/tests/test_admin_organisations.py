"""Administrator endpoints for organisations (issue #9, criteria 1 and 5)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.auth.dependencies import ADMINISTRATOR_REQUIRED, AUTHENTICATION_REQUIRED
from app.config import Settings
from app.db import utc_now
from app.errors import NOT_FOUND
from app.models import Organisation
from tests.admin_support import assert_requires_administrator, sign_in
from tests.auth_support import send_with_session
from tests.factories import create_organisation, create_session, create_user
from tests.support import LOCAL_ORIGIN, make_client

# A test value only; limits are whatever the administrator enters.
SOME_LIMIT = 7


def hosted_client(engine: Engine, database_url: str) -> TestClient:
    settings = Settings(
        database_url=database_url, allowed_origins=(LOCAL_ORIGIN,), instance_mode="hosted"
    )
    return make_client(settings=settings, engine=engine)


def as_naive_utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


# --- create ---------------------------------------------------------------------------------


def test_self_hosted_organisation_starts_active_with_its_access_period(
    client: TestClient, engine: Engine
) -> None:
    sign_in(client, engine, role="admin")
    before = utc_now()

    response = client.post(
        "/admin/organisations",
        json={
            "name": "  Northwind Procurement  ",
            "seat_limit": SOME_LIMIT,
            "profile_quota": SOME_LIMIT + 1,
            "access_period_days": SOME_LIMIT + 2,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Northwind Procurement"
    assert body["status"] == "active"
    assert (body["seat_limit"], body["profile_quota"], body["access_period_days"]) == (
        SOME_LIMIT,
        SOME_LIMIT + 1,
        SOME_LIMIT + 2,
    )
    assert body["member_count"] == 0
    ends = as_naive_utc(body["access_ends_at"])
    assert (
        before + timedelta(days=SOME_LIMIT + 2)
        <= ends
        <= utc_now() + timedelta(days=SOME_LIMIT + 2)
    )
    with Session(engine) as db:
        stored = db.get_one(Organisation, uuid.UUID(body["id"]))
        assert stored.status == "active"
        assert stored.seat_limit == SOME_LIMIT
        assert stored.access_ends_at == ends


def test_hosted_organisation_starts_pending_activation(engine: Engine, database_url: str) -> None:
    client = hosted_client(engine, database_url)
    sign_in(client, engine, role="admin")

    response = client.post(
        "/admin/organisations", json={"name": "Hosted Co", "access_period_days": SOME_LIMIT}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending_activation"
    # The access period starts at activation (#42): no end date yet.
    assert body["access_ends_at"] is None
    assert body["access_period_days"] == SOME_LIMIT


@pytest.mark.parametrize(
    "limits",
    [{}, {"seat_limit": None, "profile_quota": None, "access_period_days": None}],
    ids=["absent", "null"],
)
def test_limits_left_empty_mean_unlimited(
    client: TestClient, engine: Engine, limits: dict[str, Any]
) -> None:
    sign_in(client, engine, role="admin")

    response = client.post("/admin/organisations", json={"name": "Open Org", **limits})

    assert response.status_code == 201
    body = response.json()
    assert body["seat_limit"] is None
    assert body["profile_quota"] is None
    assert body["access_period_days"] is None
    assert body["access_ends_at"] is None


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "name"),
        ({"name": ""}, "name"),
        ({"name": "   "}, "name"),
        ({"name": "x" * 201}, "name"),
        ({"name": "Org", "seat_limit": 0}, "seat_limit"),
        ({"name": "Org", "seat_limit": -3}, "seat_limit"),
        ({"name": "Org", "profile_quota": 0}, "profile_quota"),
        ({"name": "Org", "profile_quota": -1}, "profile_quota"),
        ({"name": "Org", "access_period_days": 0}, "access_period_days"),
        ({"name": "Org", "access_period_days": -30}, "access_period_days"),
        ({"name": "Org", "seat_limit": 1.5}, "seat_limit"),
        ({"name": "Org", "seat_limit": "5"}, "seat_limit"),
        ({"name": "Org", "seat_limit": True}, "seat_limit"),
        ({"name": "Org", "seat_limit": 2**31}, "seat_limit"),
        ({"name": "Org", "colour": "blue"}, "colour"),
    ],
)
def test_invalid_organisation_is_refused_with_422(
    client: TestClient, engine: Engine, body: dict[str, Any], field: str
) -> None:
    sign_in(client, engine, role="admin")

    response = client.post("/admin/organisations", json=body)

    assert response.status_code == 422
    assert field in [error["field"] for error in response.json()["errors"]]
    with Session(engine) as db:
        assert db.scalar(select(Organisation).where(Organisation.name == "Org")) is None


def test_validation_errors_do_not_echo_the_submitted_value(
    client: TestClient, engine: Engine
) -> None:
    sign_in(client, engine, role="admin")

    response = client.post("/admin/organisations", json={"name": "Org", "seat_limit": -987654})

    assert response.status_code == 422
    assert "987654" not in response.text


# --- list -----------------------------------------------------------------------------------


def test_list_returns_every_organisation_with_its_member_count(
    client: TestClient, engine: Engine
) -> None:
    admin = sign_in(client, engine, role="admin")
    other = create_organisation(engine, name="Second Org", seat_limit=SOME_LIMIT)
    create_user(engine, organisation_id=other)
    create_user(engine, organisation_id=other)

    response = client.get("/admin/organisations")

    assert response.status_code == 200
    organisations = response.json()["organisations"]
    assert [o["id"] for o in organisations] == [str(admin.organisation_id), str(other)]
    assert [o["member_count"] for o in organisations] == [1, 2]
    assert organisations[1]["seat_limit"] == SOME_LIMIT


# --- extend the access ----------------------------------------------------------------------


def test_administrator_sets_a_later_end_of_access(client: TestClient, engine: Engine) -> None:
    sign_in(client, engine, role="admin")
    current = utc_now() + timedelta(days=1)
    organisation_id = create_organisation(engine, access_ends_at=current)
    later = current + timedelta(days=SOME_LIMIT)

    response = client.patch(
        f"/admin/organisations/{organisation_id}", json={"access_ends_at": later.isoformat()}
    )

    assert response.status_code == 200
    assert as_naive_utc(response.json()["access_ends_at"]) == later
    with Session(engine) as db:
        assert db.get_one(Organisation, organisation_id).access_ends_at == later


def test_an_end_of_access_can_be_set_when_there_is_none_yet(
    client: TestClient, engine: Engine
) -> None:
    sign_in(client, engine, role="admin")
    organisation_id = create_organisation(engine)
    future = utc_now() + timedelta(days=SOME_LIMIT)

    response = client.patch(
        f"/admin/organisations/{organisation_id}", json={"access_ends_at": future.isoformat()}
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "shift",
    [timedelta(days=-1), timedelta(0)],
    ids=["earlier", "same"],
)
def test_an_end_of_access_not_later_than_the_current_one_is_refused(
    client: TestClient, engine: Engine, shift: timedelta
) -> None:
    sign_in(client, engine, role="admin")
    current = utc_now() + timedelta(days=SOME_LIMIT)
    organisation_id = create_organisation(engine, access_ends_at=current)

    response = client.patch(
        f"/admin/organisations/{organisation_id}",
        json={"access_ends_at": (current + shift).isoformat()},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "access_ends_at"
    with Session(engine) as db:
        assert db.get_one(Organisation, organisation_id).access_ends_at == current


def test_an_end_of_access_in_the_past_is_refused(client: TestClient, engine: Engine) -> None:
    sign_in(client, engine, role="admin")
    organisation_id = create_organisation(engine)

    response = client.patch(
        f"/admin/organisations/{organisation_id}",
        json={"access_ends_at": (utc_now() - timedelta(minutes=1)).isoformat()},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [{}, {"access_ends_at": "2999-01-01T00:00:00"}, {"access_ends_at": "soon"}],
    ids=["missing", "no time zone", "not a date"],
)
def test_an_invalid_end_of_access_is_refused(
    client: TestClient, engine: Engine, body: dict[str, Any]
) -> None:
    sign_in(client, engine, role="admin")
    organisation_id = create_organisation(engine)

    response = client.patch(f"/admin/organisations/{organisation_id}", json=body)

    assert response.status_code == 422


@pytest.mark.parametrize("organisation_id", [str(uuid.uuid4()), "not-a-uuid"])
def test_extending_an_unknown_organisation_answers_404(
    client: TestClient, engine: Engine, organisation_id: str
) -> None:
    sign_in(client, engine, role="admin")

    response = client.patch(
        f"/admin/organisations/{organisation_id}",
        json={"access_ends_at": (utc_now() + timedelta(days=1)).isoformat()},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": NOT_FOUND}


# --- access rules ---------------------------------------------------------------------------


def _admin_endpoints(engine: Engine) -> list[tuple[str, str, dict[str, Any]]]:
    organisation_id = create_organisation(engine, name="Target")
    future = (utc_now() + timedelta(days=1)).isoformat()
    return [
        ("POST", "/admin/organisations", {"json": {"name": "New Org"}}),
        ("GET", "/admin/organisations", {}),
        ("PATCH", f"/admin/organisations/{organisation_id}", {"json": {"access_ends_at": future}}),
        (
            "POST",
            f"/admin/organisations/{organisation_id}/invitations",
            {"json": {"email": "someone@example.test"}},
        ),
        ("DELETE", f"/admin/invitations/{uuid.uuid4()}", {}),
    ]


def test_every_administrator_endpoint_needs_an_administrator(
    client: TestClient, engine: Engine
) -> None:
    for method, path, kwargs in _admin_endpoints(engine):
        assert_requires_administrator(client, engine, method, path, **kwargs)


def test_a_member_gets_403_before_the_body_is_validated(client: TestClient, engine: Engine) -> None:
    member = create_user(engine)

    response = send_with_session(
        client,
        "POST",
        "/admin/organisations",
        create_session(engine, member.id),
        json={"seat_limit": -1},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": ADMINISTRATOR_REQUIRED}


def test_no_session_gets_401_before_the_body_is_validated(client: TestClient) -> None:
    response = send_with_session(client, "POST", "/admin/organisations", None, json={})

    assert response.status_code == 401
    assert response.json() == {"detail": AUTHENTICATION_REQUIRED}


def test_a_member_cannot_create_an_organisation(client: TestClient, engine: Engine) -> None:
    sign_in(client, engine, role="member")

    response = client.post("/admin/organisations", json={"name": "Sneaky Org"})

    assert response.status_code == 403
    with Session(engine) as db:
        names = db.scalars(select(Organisation.name)).all()
    assert "Sneaky Org" not in names
