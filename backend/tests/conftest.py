"""Database fixtures.

- `database_url`: URL of a migrated throwaway database for the whole run (see tests/db_support.py).
- `engine`: an engine on it; every table is emptied after each test that uses it.
- `client`: a TestClient on that database (startup not run: no first-start administrator).

Without DATABASE_URL, tests that need a database are skipped locally and fail in CI.
"""

import os
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.config import Settings
from app.db import make_engine
from app.migrate import upgrade_to_head
from tests.db_support import temporary_database, truncate_all
from tests.support import LOCAL_ORIGIN, make_client


@pytest.fixture(autouse=True)
def _fast_name_detector(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The process-wide redactor uses a fake name detector (no model, quick) in every test but
    those marked `model`, which use the real one (see tests/redaction/conftest.py)."""
    if request.node.get_closest_marker("model"):
        return
    from app.redaction import engine
    from tests.redaction.support import fake_redactor

    monkeypatch.setattr(
        engine, "_REDACTOR", fake_redactor("Anna Keller-Brandt", "Zoë Okonkwo-Lindqvist")
    )


@pytest.fixture(scope="session")
def server_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        if os.environ.get("CI"):
            pytest.fail("DATABASE_URL must be set in CI: the database tests cannot be skipped")
        pytest.skip("DATABASE_URL is not set: tests that need PostgreSQL are skipped")
    return url


@pytest.fixture(scope="session")
def database_url(server_url: str) -> Iterator[str]:
    with temporary_database(server_url) as url:
        engine = make_engine(url)
        try:
            with engine.connect() as connection:
                upgrade_to_head(connection)
                connection.commit()
        finally:
            engine.dispose()
        yield url


@pytest.fixture(scope="session")
def _shared_engine(database_url: str) -> Iterator[Engine]:
    engine = make_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def engine(_shared_engine: Engine) -> Iterator[Engine]:
    yield _shared_engine
    truncate_all(_shared_engine)


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        allowed_origins=(LOCAL_ORIGIN,),
        run_budget_eur=Decimal(5),
    )


@pytest.fixture
def client(engine: Engine, settings: Settings) -> TestClient:
    return make_client(settings=settings, engine=engine)
