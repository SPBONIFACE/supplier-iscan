"""Contract test: the identity endpoints answer as openapi.yaml describes."""

import uuid
from typing import Any

from sqlalchemy import Engine

from app.config import Settings
from app.identity.services import build_identity_services
from app.registries import RegistrySearchService
from tests.auth_support import send_with_session
from tests.contract.test_auth_contract import assert_matches_contract
from tests.contract.test_openapi_contract import load_contract
from tests.factories import create_session, create_user
from tests.identity.support import FakeRegistries, candidate, found, make_harness, proposal


def test_identity_responses_match_the_contract(engine: Engine, settings: Settings) -> None:
    other = candidate("Acme Holdings", lei="213800OTHER0000000AA", wikidata_id="Q2")
    harness = make_harness(
        engine,
        settings,
        FakeRegistries(found(candidate(), other), found(failed=("gleif", "wikidata"))),
        [proposal("lei:529900ACME00000000AA")],
    )
    token = create_session(engine, create_user(engine).id)

    def call(method: str, template: str, path: str, expected: int, **kwargs: Any) -> Any:
        response = send_with_session(harness.client, method.upper(), path, token, **kwargs)
        assert response.status_code == expected, (path, response.text)
        assert_matches_contract(response, template, method)
        return response

    body = {"name": "Acme", "profile_language": "en", "ui_language": "fr"}
    call("get", "/identity/disclosure", "/identity/disclosure?language=fr", 200)
    call("post", "/identity-sessions", "/identity-sessions", 422, json={**body, "name": "​"})
    session = call("post", "/identity-sessions", "/identity-sessions", 201, json=body).json()
    base = f"/identity-sessions/{session['id']}"
    missing = f"/identity-sessions/{uuid.uuid4()}"
    call("get", "/identity-sessions/{id}", base, 200)
    call("get", "/identity-sessions/{id}", missing, 404)
    call("get", "/identity-sessions/{id}/candidates", f"{base}/candidates", 200)
    call("post", "/identity-sessions/{id}/website", f"{base}/website", 422, json={"website": "x y"})
    call(
        "post",
        "/identity-sessions/{id}/website",
        f"{base}/website",
        200,
        json={"website": "acme.example"},
    )
    call("post", "/identity-sessions/{id}/messages", f"{base}/messages", 422, json={"text": " "})
    call(
        "post",
        "/identity-sessions/{id}/confirm",
        f"{base}/confirm",
        422,
        json={"candidate_id": "x"},
    )
    confirmed = call(
        "post",
        "/identity-sessions/{id}/confirm",
        f"{base}/confirm",
        200,
        json={"candidate_id": "lei:529900ACME00000000AA"},
    ).json()
    assert confirmed["natural_person"] is False
    call(
        "post",
        "/identity-sessions/{id}/confirm",
        f"{base}/confirm",
        409,
        json={"candidate_id": "x"},
    )
    call("post", "/identity-sessions/{id}/messages", f"{base}/messages", 409, json={"text": "hi"})
    # Both registries down: a notice turn in a 201, never an error response.
    down = call("post", "/identity-sessions", "/identity-sessions", 201, json=body).json()
    assert down["registries"] == {"gleif": "unreachable", "wikidata": "unreachable"}


def test_every_identity_operation_requires_the_session_cookie() -> None:
    paths = load_contract()["paths"]
    templates = [path for path in paths if path.startswith("/identity")]
    assert len(templates) == 7
    for template in templates:
        for operation in paths[template].values():
            assert operation["security"] == [{"sessionCookie": []}]
            assert "401" in operation["responses"]


def test_the_default_services_use_the_registry_service_on_the_guarded_client() -> None:
    services = build_identity_services()
    try:
        assert isinstance(services.registries, RegistrySearchService)
    finally:
        services.close()
