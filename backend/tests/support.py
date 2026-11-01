"""Shared helpers for the backend tests."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.config import Settings
from app.health import DatabaseCheck
from app.main import create_app
from app.providers import Providers, load_catalogue
from tests.providers.support import make_meter

LOCAL_ORIGIN = "http://localhost:5173"

# A port nothing listens on: the real database check fails fast with "connection refused".
UNREACHABLE_DATABASE_URL = "postgresql://nobody:nothing@127.0.0.1:1/none"

# The selected provider configurations of the shipped example need these two keys.
EXAMPLE_KEY_SETTINGS = ["GEMINI_API_KEY", "PERPLEXITY_API_KEY"]

# HTTPS, so that the client's cookie jar keeps and sends the `Secure` session cookie.
BASE_URL = "https://testserver"


def make_client(
    database_check: DatabaseCheck | None = None,
    database_url: str | None = None,
    allowed_origins: tuple[str, ...] = (LOCAL_ORIGIN,),
    settings: Settings | None = None,
    engine: Engine | None = None,
    providers: Providers | None = None,
) -> TestClient:
    """A client on an application whose startup (migrations, first-start setup) does not run.

    Use `with TestClient(create_app(...)) as client:` to run the startup.
    """
    settings = settings or Settings(database_url=database_url, allowed_origins=allowed_origins)
    # No provider key, whatever the developer's environment holds: the tests never see real keys.
    providers = providers or Providers(load_catalogue(), environ={}, meter=make_meter())
    # raise_server_exceptions=False: an unhandled error shows up as a 500, as in production.
    return TestClient(
        create_app(settings, database_check=database_check, engine=engine, providers=providers),
        base_url=BASE_URL,
        raise_server_exceptions=False,
    )
