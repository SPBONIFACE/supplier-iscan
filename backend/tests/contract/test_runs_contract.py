"""Contract test: the run endpoints answer as openapi.yaml describes."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.auth_support import send_with_session
from tests.contract.test_auth_contract import assert_matches_contract
from tests.contract.test_openapi_contract import load_contract
from tests.factories import create_session, create_user
from tests.runs_support import add_usage, create_identity, create_run


def test_run_responses_match_the_contract(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    identity_id = create_identity(engine, user.organisation_id)
    paused = create_run(engine, user.organisation_id, status="paused", enqueue=False)
    finished = create_run(engine, user.organisation_id, status="completed", enqueue=False)
    running = create_run(engine, user.organisation_id, status="running", enqueue=False)
    add_usage(engine, user.organisation_id, running)
    missing = "00000000-0000-0000-0000-000000000000"
    cases: list[tuple[str, str, str, dict[str, Any], int]] = [
        ("post", "/runs", "/runs", {"json": {"identity_id": str(identity_id)}}, 202),
        ("post", "/runs", "/runs", {"json": {"identity_id": missing}}, 404),
        ("post", "/runs", "/runs", {"json": {}}, 422),
        ("get", "/runs", "/runs", {}, 200),
        ("get", "/runs/{id}", f"/runs/{running}", {}, 200),
        ("get", "/runs/{id}", f"/runs/{missing}", {}, 404),
        ("post", "/runs/{id}/stop", f"/runs/{finished}/stop", {}, 409),
        ("post", "/runs/{id}/resume", f"/runs/{finished}/resume", {}, 409),
        ("post", "/runs/{id}/resume", f"/runs/{paused}/resume", {}, 202),
        ("post", "/runs/{id}/stop", f"/runs/{running}/stop", {}, 200),
    ]

    for method, template, path, kwargs, expected in cases:
        response = send_with_session(client, method.upper(), path, token, **kwargs)
        assert response.status_code == expected, (path, response.text)
        assert_matches_contract(response, template, method)


def test_every_run_operation_requires_the_session_cookie() -> None:
    paths = load_contract()["paths"]
    for template in (
        "/runs",
        "/runs/{id}",
        "/runs/{id}/stop",
        "/runs/{id}/resume",
        "/runs/{id}/criteria",
        "/runs/{id}/fit",
        "/runs/{id}/buyer-context",
        "/runs/{id}/recommendations",
        "/runs/{id}/buyer-inputs/{field}",
    ):
        for operation in paths[template].values():
            assert operation["security"] == [{"sessionCookie": []}]
            assert "401" in operation["responses"]
