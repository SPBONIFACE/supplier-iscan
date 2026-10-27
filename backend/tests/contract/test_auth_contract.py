"""Contract test: the auth endpoints answer as openapi.yaml describes."""

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.auth.sessions import SESSION_COOKIE_NAME
from tests.auth_support import send_with_session
from tests.contract.test_openapi_contract import load_contract, response_validator
from tests.factories import create_user
from tests.support import UNREACHABLE_DATABASE_URL, make_client


def assert_matches_contract(response: httpx2.Response, path: str, method: str) -> None:
    responses = load_contract()["paths"][path][method]["responses"]
    assert str(response.status_code) in responses, f"{response.status_code} not documented"
    if response.status_code == 204:
        assert response.content == b""
        return
    assert response.headers["content-type"].startswith("application/json")
    validator = response_validator(load_contract(), path, method, response.status_code)
    validator.validate(response.json())


def test_contract_declares_the_session_cookie_scheme() -> None:
    contract = load_contract()
    scheme = contract["components"]["securitySchemes"]["sessionCookie"]

    assert scheme == {**scheme, "type": "apiKey", "in": "cookie", "name": SESSION_COOKIE_NAME}
    assert "security" not in contract["paths"]["/auth/login"]["post"]
    for path, method in (("/auth/logout", "post"), ("/auth/me", "get")):
        assert contract["paths"][path][method]["security"] == [{"sessionCookie": []}]
        assert "401" in contract["paths"][path][method]["responses"]


def test_login_responses_match_the_contract(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    answers = [
        client.post("/auth/login", json={"email": user.email, "password": user.password}),
        client.post("/auth/login", json={"email": user.email, "password": "wrong"}),
        client.post("/auth/login", json={"email": "", "password": ""}),
    ]

    assert [answer.status_code for answer in answers] == [200, 401, 422]
    for answer in answers:
        assert_matches_contract(answer, "/auth/login", "post")


def test_login_503_matches_the_contract() -> None:
    response = make_client(database_url=UNREACHABLE_DATABASE_URL).post(
        "/auth/login", json={"email": "a@example.test", "password": "secret"}
    )

    assert response.status_code == 503
    assert_matches_contract(response, "/auth/login", "post")


def test_me_and_logout_responses_match_the_contract(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    client.post("/auth/login", json={"email": user.email, "password": user.password})

    me = client.get("/auth/me")
    logout = client.post("/auth/logout")
    me_after = send_with_session(client, "GET", "/auth/me", None)
    logout_after = send_with_session(client, "POST", "/auth/logout", None)

    assert [r.status_code for r in (me, logout, me_after, logout_after)] == [200, 204, 401, 401]
    assert_matches_contract(me, "/auth/me", "get")
    assert_matches_contract(me_after, "/auth/me", "get")
    assert_matches_contract(logout, "/auth/logout", "post")
    assert_matches_contract(logout_after, "/auth/logout", "post")


@pytest.mark.parametrize(("path", "method"), [("/auth/me", "GET"), ("/auth/logout", "POST")])
def test_protected_503_matches_the_contract(path: str, method: str) -> None:
    response = send_with_session(
        make_client(database_url=UNREACHABLE_DATABASE_URL), method, path, "some-token"
    )

    assert response.status_code == 503
    assert_matches_contract(response, path, method.lower())
