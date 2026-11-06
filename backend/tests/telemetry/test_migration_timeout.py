"""Migrations run without a statement timeout (#51 QA), whatever the request timeout is."""

import pytest
from sqlalchemy import Connection, text

from app.auth import bootstrap
from app.config import Settings
from app.db import make_engine


def test_startup_migrations_are_not_cut_by_the_request_statement_timeout(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = make_engine(database_url, statement_timeout_seconds=1)
    seen: list[str] = []

    def slow_upgrade(connection: Connection) -> None:
        connection.execute(text("SELECT pg_sleep(2)"))  # longer than the request timeout
        seen.append(str(connection.execute(text("SHOW statement_timeout")).scalar()))

    monkeypatch.setattr(bootstrap, "upgrade_to_head", slow_upgrade)
    monkeypatch.setattr(bootstrap, "ensure_local_administrator", lambda db, settings: False)
    try:
        bootstrap.prepare_database(engine, Settings(database_url=None, allowed_origins=("x",)))
        with engine.connect() as connection:  # the pooled connection is back to the request value
            assert connection.execute(text("SHOW statement_timeout")).scalar() == "1s"
    finally:
        engine.dispose()

    assert seen == ["0"]
