from tests.support import UNREACHABLE_DATABASE_URL, make_client


def test_health_returns_200_when_database_is_available() -> None:
    response = make_client(database_check=lambda: True).get("/health")

    assert response.status_code == 200
    assert response.json() == {"api": "available", "database": "available"}


def test_health_returns_503_when_database_check_fails() -> None:
    response = make_client(database_check=lambda: False).get("/health")

    assert response.status_code == 503
    assert response.json() == {"api": "available", "database": "unavailable"}


def test_health_returns_503_without_details_when_database_is_unreachable() -> None:
    # Real check against a closed port: no crash, no stack trace, no connection string in the body.
    response = make_client(database_url=UNREACHABLE_DATABASE_URL).get("/health")

    assert response.status_code == 503
    assert response.json() == {"api": "available", "database": "unavailable"}
    assert "Traceback" not in response.text
    assert "127.0.0.1" not in response.text


def test_health_returns_503_when_database_url_is_not_set() -> None:
    response = make_client(database_url=None).get("/health")

    assert response.status_code == 503
    assert response.json() == {"api": "available", "database": "unavailable"}


def test_health_returns_503_when_database_url_is_malformed() -> None:
    response = make_client(database_url="not a connection string").get("/health")

    assert response.status_code == 503
    assert response.json() == {"api": "available", "database": "unavailable"}


def test_interactive_documentation_pages_are_disabled() -> None:
    client = make_client(database_check=lambda: True)

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_generated_openapi_schema_is_not_served() -> None:
    # openapi.yaml is the only contract: FastAPI's generated schema must not be exposed.
    client = make_client(database_check=lambda: True)

    assert client.get("/openapi.json").status_code == 404
