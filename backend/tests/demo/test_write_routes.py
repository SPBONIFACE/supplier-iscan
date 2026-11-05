"""Every state-changing route of the contract is refused to the demo and to a visitor, and the demo
reaches only demo copies (#50, QA). The routes come from `openapi.yaml`, so a new route is covered
without editing this file."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import Base
from app.demo.readonly import READ_ONLY
from app.models import DemoProfile
from tests.auth_support import send_with_session
from tests.contract.test_openapi_contract import load_contract
from tests.demo.support import AUTHOR, PERSON, client_with_recording_provider
from tests.demo.test_demo import two_profiles
from tests.factories import create_organisation, create_session, create_user
from tests.runs_support import create_run

WRITE_METHODS = ("post", "put", "patch", "delete")


def write_operations() -> list[tuple[str, str, bool]]:
    """(method, path template, needs a session) for every state-changing operation in the contract
    that is not itself under /demo."""
    found = []
    for path, item in load_contract()["paths"].items():
        for method in WRITE_METHODS:
            operation = item.get(method)
            if operation is not None:
                found.append((method, path, bool(operation.get("security"))))
    return found


def concrete(path: str) -> str:
    out = path
    while "{" in out:
        start = out.index("{")
        out = out[:start] + str(uuid.uuid4()) + out[out.index("}") + 1 :]
    return out


def row_counts(engine: Engine) -> dict[str, int]:
    with Session(engine) as db:
        return {
            table.name: db.scalar(select(func.count()).select_from(table)) or 0
            for table in Base.metadata.sorted_tables
        }


def test_the_contract_lists_the_write_routes() -> None:
    operations = write_operations()

    assert len(operations) >= 20  # a guard against a parser that finds nothing
    assert not [path for _, path, _ in operations if path.startswith("/demo")]  # demo has no write


def test_every_write_route_is_refused_without_a_session(engine: Engine, settings: Settings) -> None:
    demo, _ = two_profiles(engine, settings)
    recording = client_with_recording_provider(engine, demo.settings)
    before = row_counts(engine)

    for method, path, needs_session in write_operations():
        for body in ({}, {"identity_id": str(uuid.uuid4()), "text": "x", "version": 1}):
            response = recording.client.request(method.upper(), concrete(path), json=body)
            if needs_session:
                assert response.status_code == 401, (method, path, response.status_code)
            else:  # login, invitation acceptance: public by design, refused for these inputs
                assert 400 <= response.status_code < 500, (method, path, response.status_code)

    assert row_counts(engine) == before  # nothing written, no job queued, no usage recorded
    assert recording.adapter.calls == []  # no LLM call


def test_every_write_route_is_refused_with_403_under_the_demo(
    engine: Engine, settings: Settings
) -> None:
    demo, profiles = two_profiles(engine, settings)
    recording = client_with_recording_provider(engine, demo.settings)
    member = create_user(engine, organisation_id=demo.organisation_id)
    token = create_session(engine, member.id)
    before = row_counts(engine)
    count = 0

    for method, path, _ in write_operations():
        # The demo's access to the same route, with a real demo id where the path takes an id.
        target = "/demo" + concrete(path)
        for session in (None, token):
            response = send_with_session(
                recording.client, method.upper(), target, session, json={"x": 1}
            )
            assert response.status_code == 403, (method, target, response.status_code)
            assert response.json() == {"detail": READ_ONLY}
        # ... and on the demo's own read routes.
        response = recording.client.request(method.upper(), f"/demo/profiles/{profiles[0].id}")
        assert response.status_code == 403
        count += 1

    assert count == len(write_operations())
    assert row_counts(engine) == before
    assert recording.adapter.calls == []


def real_ids(engine: Engine) -> list[uuid.UUID]:
    """Every primary key of every table that holds organisation data (not the demo copies)."""
    ids: list[uuid.UUID] = []
    with Session(engine) as db:
        for table in Base.metadata.sorted_tables:
            if table.name == DemoProfile.__tablename__ or "id" not in table.c:
                continue
            ids.extend(
                value for (value,) in db.execute(select(table.c.id)) if isinstance(value, uuid.UUID)
            )
    return ids


def test_demo_routes_reach_only_demo_copies(engine: Engine, settings: Settings) -> None:
    demo, profiles = two_profiles(engine, settings)
    other = create_organisation(engine, name="Another buyer")
    create_run(engine, other, "Customer Supplier", status="completed", enqueue=False)
    user = create_user(engine, organisation_id=other)
    create_session(engine, user.id)
    client = TestClient(
        client_with_recording_provider(engine, demo.settings).client.app,
        base_url="https://testserver",
        raise_server_exceptions=False,
    )
    ids = real_ids(engine)
    assert len(ids) > 10  # runs, identities, facts, statements, organisations, users, sessions...
    demo_ids = {profile.id for profile in profiles}
    assert not demo_ids & set(ids)  # a demo id is never a real id

    for real in ids:
        assert client.get(f"/demo/profiles/{real}").status_code == 404, real
        assert client.get(f"/demo/profiles/{real}/pdf").status_code in (404,), real
        mixed = client.get(
            "/demo/comparison", params={"profile_ids": [str(profiles[0].id), str(real)]}
        )
        assert mixed.status_code == 404 and "Acme" not in mixed.text, real
    # Guessing: random ids and near-misses of a real demo id.
    near = str(profiles[0].id)[:-1] + ("0" if str(profiles[0].id)[-1] != "0" else "1")
    for guess in (str(uuid.uuid4()), near, "0" * 32, "../runs", "1' OR '1'='1"):
        assert client.get(f"/demo/profiles/{guess}").status_code == 404, guess
    # What a demo response holds comes from the copies: nothing of the originals.
    body: Any = client.get(f"/demo/profiles/{profiles[0].id}").text
    for hidden in (PERSON, AUTHOR, str(demo.run_id), str(demo.organisation_id), str(other)):
        assert hidden not in body


@pytest.mark.parametrize("path", ["/demo/profiles", "/demo/comparison", "/demo/profile-definition"])
def test_demo_reads_stay_reads(engine: Engine, settings: Settings, path: str) -> None:
    demo, profiles = two_profiles(engine, settings)
    client = client_with_recording_provider(engine, demo.settings).client
    before = row_counts(engine)

    client.get(path, params={"profile_ids": [str(p.id) for p in profiles]})

    assert row_counts(engine) == before
