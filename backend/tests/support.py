"""Shared helpers for the backend tests."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.health import DatabaseCheck
from app.main import create_app

LOCAL_ORIGIN = "http://localhost:5173"

# A port nothing listens on: the real database check fails fast with "connection refused".
UNREACHABLE_DATABASE_URL = "postgresql://nobody:nothing@127.0.0.1:1/none"


def make_client(
    database_check: DatabaseCheck | None = None,
    database_url: str | None = None,
    allowed_origins: tuple[str, ...] = (LOCAL_ORIGIN,),
) -> TestClient:
    settings = Settings(database_url=database_url, allowed_origins=allowed_origins)
    # raise_server_exceptions=False: an unhandled error shows up as a 500, as in production.
    return TestClient(
        create_app(settings, database_check=database_check), raise_server_exceptions=False
    )
