import pytest

from app.config import DEFAULT_ALLOWED_ORIGINS, ConfigurationError, load_settings
from tests.support import LOCAL_ORIGIN, make_client

ALLOW_ORIGIN = "access-control-allow-origin"


def test_allowed_origin_gets_allow_header() -> None:
    response = make_client(database_check=lambda: True).get(
        "/health", headers={"Origin": LOCAL_ORIGIN}
    )

    assert response.headers[ALLOW_ORIGIN] == LOCAL_ORIGIN


def test_other_origin_gets_no_allow_header() -> None:
    response = make_client(database_check=lambda: True).get(
        "/health", headers={"Origin": "http://localhost:3000"}
    )

    assert ALLOW_ORIGIN not in response.headers


def test_preflight_from_allowed_origin_is_accepted() -> None:
    response = make_client(database_check=lambda: True).options(
        "/health",
        headers={"Origin": LOCAL_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers[ALLOW_ORIGIN] == LOCAL_ORIGIN


def test_preflight_from_other_origin_is_rejected() -> None:
    response = make_client(database_check=lambda: True).options(
        "/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 400
    assert ALLOW_ORIGIN not in response.headers


def test_allowed_origin_comes_from_configuration() -> None:
    settings = load_settings({"CORS_ALLOWED_ORIGINS": "https://app.example.test"})
    client = make_client(database_check=lambda: True, allowed_origins=settings.allowed_origins)

    allowed = client.get("/health", headers={"Origin": "https://app.example.test"})
    local = client.get("/health", headers={"Origin": LOCAL_ORIGIN})

    assert allowed.headers[ALLOW_ORIGIN] == "https://app.example.test"
    assert ALLOW_ORIGIN not in local.headers


def test_default_origin_is_the_local_frontend() -> None:
    assert load_settings({}).allowed_origins == (DEFAULT_ALLOWED_ORIGINS,)
    assert DEFAULT_ALLOWED_ORIGINS == LOCAL_ORIGIN


def test_several_origins_are_comma_separated() -> None:
    settings = load_settings({"CORS_ALLOWED_ORIGINS": " https://a.test , https://b.test "})

    assert settings.allowed_origins == ("https://a.test", "https://b.test")


@pytest.mark.parametrize("value", ["*", "http://localhost:5173,*", "https://*.example.test"])
def test_wildcard_origin_is_refused(value: str) -> None:
    with pytest.raises(ConfigurationError):
        load_settings({"CORS_ALLOWED_ORIGINS": value})


def test_origin_list_with_no_origin_is_refused() -> None:
    with pytest.raises(ConfigurationError):
        load_settings({"CORS_ALLOWED_ORIGINS": " , "})


def test_preflight_for_login_allows_credentials_from_the_allowed_origin() -> None:
    # The frontend sends the session cookie cross-origin (localhost:5173 -> localhost:8000).
    response = make_client(database_check=lambda: True).options(
        "/auth/login",
        headers={
            "Origin": LOCAL_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers[ALLOW_ORIGIN] == LOCAL_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_preflight_for_login_from_other_origin_is_rejected() -> None:
    response = make_client(database_check=lambda: True).options(
        "/auth/login",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 400
    assert ALLOW_ORIGIN not in response.headers
