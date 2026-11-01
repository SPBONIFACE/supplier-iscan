"""Shared check for organisation isolation (spec, Security model). Every issue that adds a member
endpoint on organisation-owned data calls it:

    def make_run(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
        run_id = create_run(engine, owner.id, supplier_name="Distinctive Supplier SA")
        return OwnedResource(
            path=f"/runs/{run_id}",
            missing_path=f"/runs/{uuid.uuid4()}",
            marker="Distinctive Supplier SA",
        )

    def test_runs_are_isolated(client: TestClient, engine: Engine) -> None:
        assert_organisation_isolation(client, engine, "GET", make_run)

It creates the owning organisation, another organisation and an administrator who is a member of
a third one, then asserts:

- 401 for every kind of missing or bad session (`assert_requires_session`);
- for an endpoint on one resource (`missing_path` given): 404 for a member of the other
  organisation and for the administrator, with exactly the body of a non-existent id;
- for an organisation-wide endpoint (`missing_path=None`, e.g. a list or `GET /organisation`):
  the other member and the administrator get their own organisation's answer;
- in every case, their answer never contains `marker`; the owning member's answer is a success
  and, for a GET, contains it. The owning member goes last, so DELETE endpoints work too.
"""

import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx2
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.auth_support import assert_requires_session, send_with_session
from tests.factories import TestUser, create_organisation, create_session, create_user


@dataclass(frozen=True)
class OwnerOrganisation:
    id: uuid.UUID
    name: str


@dataclass(frozen=True)
class OwnedResource:
    """The endpoint for a resource of the owning organisation."""

    path: str
    # The same endpoint for an id that does not exist; None for an organisation-wide endpoint.
    missing_path: str | None
    # A value only the owning organisation's answer contains (a name, a quote...).
    marker: str


MakeResource = Callable[[Engine, OwnerOrganisation], OwnedResource]


def _send(
    client: TestClient, engine: Engine, user: TestUser, method: str, path: str, **kwargs: Any
) -> httpx2.Response:
    return send_with_session(client, method, path, create_session(engine, user.id), **kwargs)


def assert_organisation_isolation(
    client: TestClient,
    engine: Engine,
    method: str,
    make_resource: MakeResource,
    **kwargs: Any,
) -> None:
    suffix = secrets.token_hex(4)
    owner_organisation = OwnerOrganisation(
        create_organisation(engine, name=f"Owner organisation {suffix}"),
        f"Owner organisation {suffix}",
    )
    other_organisation = create_organisation(engine, name=f"Other organisation {suffix}")
    administrator_organisation = create_organisation(engine, name=f"Admin organisation {suffix}")
    owner = create_user(engine, organisation_id=owner_organisation.id)
    other = create_user(engine, organisation_id=other_organisation)
    administrator = create_user(engine, role="admin", organisation_id=administrator_organisation)

    resource = make_resource(engine, owner_organisation)
    where = f"{method} {resource.path}"

    # A member of the other organisation: whatever the endpoint answers, never 401 when valid.
    assert_requires_session(client, engine, method, resource.path, user=other, **kwargs)

    missing_body: Any = None
    if resource.missing_path is not None:
        missing = _send(client, engine, owner, method, resource.missing_path, **kwargs)
        assert missing.status_code == 404, f"{method} {resource.missing_path}: {missing.text}"
        missing_body = missing.json()

    for label, user in (("other organisation", other), ("administrator", administrator)):
        response = _send(client, engine, user, method, resource.path, **kwargs)
        assert resource.marker not in response.text, f"{where} leaks to the {label}"
        if resource.missing_path is not None:
            assert response.status_code == 404, f"{where}, {label}: {response.status_code}"
            assert response.json() == missing_body, f"{where}, {label}: body differs from absent"
        else:
            assert response.status_code < 400, f"{where}, {label}: {response.status_code}"

    response = _send(client, engine, owner, method, resource.path, **kwargs)
    assert response.status_code < 400, f"{where}, owning member: {response.status_code}"
    if method.upper() == "GET":
        assert resource.marker in response.text, f"{where}: the owning member misses it"
