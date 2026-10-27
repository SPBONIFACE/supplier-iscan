"""Contract test: organisation, invitation and user endpoints answer as openapi.yaml describes."""

import uuid
from datetime import timedelta

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.db import utc_now
from tests.admin_support import sign_in
from tests.auth_support import send_with_session
from tests.contract.test_auth_contract import assert_matches_contract
from tests.contract.test_openapi_contract import load_contract
from tests.factories import create_invitation, create_organisation, create_user
from tests.support import UNREACHABLE_DATABASE_URL, make_client

PASSWORD = "a long enough password for any test setting"


def check(response: httpx2.Response, path: str, method: str, status: int) -> None:
    assert response.status_code == status, response.text
    assert_matches_contract(response, path, method)


def test_admin_operations_declare_the_session_and_403() -> None:
    for path, operations in load_contract()["paths"].items():
        if not path.startswith("/admin/"):
            continue
        for operation in operations.values():
            assert operation["security"] == [{"sessionCookie": []}], path
            assert {"401", "403"} <= set(operation["responses"]), path


def test_organisation_responses_match_the_contract(client: TestClient, engine: Engine) -> None:
    path, item = "/admin/organisations", "/admin/organisations/{id}"
    admin = sign_in(client, engine, role="admin")
    future = (utc_now() + timedelta(days=2)).isoformat()

    created = client.post(path, json={"name": "Contract Org", "access_period_days": 1})
    check(created, path, "post", 201)
    check(client.post(path, json={"name": ""}), path, "post", 422)
    check(client.get(path), path, "get", 200)
    organisation_id = created.json()["id"]
    check(
        client.patch(f"/admin/organisations/{organisation_id}", json={"access_ends_at": future}),
        item,
        "patch",
        200,
    )
    check(
        client.patch(f"/admin/organisations/{organisation_id}", json={"access_ends_at": future}),
        item,
        "patch",
        422,
    )
    check(
        client.patch(f"/admin/organisations/{uuid.uuid4()}", json={"access_ends_at": future}),
        item,
        "patch",
        404,
    )

    check(send_with_session(client, "GET", path, None), path, "get", 401)
    sign_in(client, engine, role="member", organisation_id=admin.organisation_id)
    check(client.get(path), path, "get", 403)
    check(client.post(path, json={"name": "x"}), path, "post", 403)
    check(
        client.patch(f"/admin/organisations/{organisation_id}", json={"access_ends_at": future}),
        item,
        "patch",
        403,
    )


def test_invitation_responses_match_the_contract(client: TestClient, engine: Engine) -> None:
    create, revoke = "/admin/organisations/{id}/invitations", "/admin/invitations/{id}"
    check_path, accept_path = "/invitations/{token}", "/invitations/{token}/accept"
    sign_in(client, engine, role="admin")
    organisation_id = create_organisation(engine, seat_limit=1)
    taken = create_user(engine)

    created = client.post(
        f"/admin/organisations/{organisation_id}/invitations", json={"email": "c@example.test"}
    )
    check(created, create, "post", 201)
    check(
        client.post(
            f"/admin/organisations/{organisation_id}/invitations", json={"email": taken.email}
        ),
        create,
        "post",
        409,
    )
    check(
        client.post(f"/admin/organisations/{organisation_id}/invitations", json={"email": "bad"}),
        create,
        "post",
        422,
    )
    check(
        client.post(
            f"/admin/organisations/{uuid.uuid4()}/invitations", json={"email": "c@example.test"}
        ),
        create,
        "post",
        404,
    )

    token = created.json()["link"].rsplit("/", 1)[1]
    check(client.get(f"/invitations/{token}"), check_path, "get", 200)
    check(client.get("/invitations/unknown"), check_path, "get", 404)
    check(
        client.post(f"/invitations/{token}/accept", json={"password": "short"}),
        accept_path,
        "post",
        422,
    )
    check(
        client.post(f"/invitations/{token}/accept", json={"password": PASSWORD}),
        accept_path,
        "post",
        200,
    )
    check(
        client.post(f"/invitations/{token}/accept", json={"password": PASSWORD}),
        accept_path,
        "post",
        404,
    )
    full = create_invitation(engine, organisation_id)
    check(
        client.post(f"/invitations/{full.token}/accept", json={"password": PASSWORD}),
        accept_path,
        "post",
        409,
    )

    sign_in(client, engine, role="admin")
    check(client.delete(f"/admin/invitations/{full.id}"), revoke, "delete", 204)
    check(client.delete(f"/admin/invitations/{created.json()['id']}"), revoke, "delete", 409)
    check(client.delete(f"/admin/invitations/{uuid.uuid4()}"), revoke, "delete", 404)
    sign_in(client, engine, role="member")
    check(client.delete(f"/admin/invitations/{full.id}"), revoke, "delete", 403)
    check(
        send_with_session(client, "DELETE", f"/admin/invitations/{full.id}", None),
        revoke,
        "delete",
        401,
    )


def test_user_responses_match_the_contract(client: TestClient, engine: Engine) -> None:
    path = "/users/{id}"
    member = sign_in(client, engine)

    check(client.get(f"/users/{member.id}"), path, "get", 200)
    check(client.get(f"/users/{uuid.uuid4()}"), path, "get", 404)
    check(send_with_session(client, "GET", f"/users/{member.id}", None), path, "get", 401)


@pytest.mark.parametrize(
    ("method", "path", "template", "body"),
    [
        ("GET", "/admin/organisations", "/admin/organisations", None),
        ("GET", f"/users/{uuid.uuid4()}", "/users/{id}", None),
        ("GET", "/invitations/some-token", "/invitations/{token}", None),
        (
            "POST",
            "/invitations/some-token/accept",
            "/invitations/{token}/accept",
            {"password": PASSWORD},
        ),
    ],
)
def test_503_matches_the_contract(
    method: str, path: str, template: str, body: dict[str, str] | None
) -> None:
    client = make_client(database_url=UNREACHABLE_DATABASE_URL)
    kwargs = {"json": body} if body is not None else {}

    response = send_with_session(client, method, path, "some-token", **kwargs)

    check(response, template, method.lower(), 503)
