"""Alembic migrations: one head, reversible, and in step with the models."""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect

from app.auth.bootstrap import prepare_database
from app.config import Settings
from app.db import Base, make_engine
from app.migrate import alembic_config, upgrade_to_head
from tests.db_support import temporary_database
from tests.support import LOCAL_ORIGIN

TABLES = {"organisations", "users", "sessions", "usage_events", "invitations"}


@pytest.fixture
def empty_engine(server_url: str) -> Iterator[Engine]:
    with temporary_database(server_url) as url:
        engine = make_engine(url)
        yield engine
        engine.dispose()


def test_migrations_have_a_single_head() -> None:
    # Two branches that each add a migration on the same parent fail here, not in production.
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()

    assert len(heads) == 1, f"several migration heads: {heads}"


def test_upgrade_downgrade_and_upgrade_again(empty_engine: Engine) -> None:
    with empty_engine.connect() as connection:
        upgrade_to_head(connection)
        connection.commit()
    assert TABLES <= set(inspect(empty_engine).get_table_names())

    with empty_engine.connect() as connection:
        command.downgrade(alembic_config(connection), "base")
        connection.commit()
    assert set(inspect(empty_engine).get_table_names()) <= {"alembic_version"}

    with empty_engine.connect() as connection:
        upgrade_to_head(connection)
        connection.commit()
    assert TABLES <= set(inspect(empty_engine).get_table_names())


def test_models_match_the_migrations(empty_engine: Engine) -> None:
    with empty_engine.connect() as connection:
        upgrade_to_head(connection)
        connection.commit()
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        differences = compare_metadata(context, Base.metadata)

    assert differences == [], "models changed without a migration: run alembic --autogenerate"


def test_startup_migrates_an_empty_database_and_creates_the_administrator(
    empty_engine: Engine,
) -> None:
    settings = Settings(
        database_url="unused: the engine is given",
        allowed_origins=(LOCAL_ORIGIN,),
        admin_email="admin@example.test",
        admin_password="first-start password",  # noqa: S106 - test credential
    )

    prepare_database(empty_engine, settings)
    prepare_database(empty_engine, settings)  # a restart is a no-op

    assert TABLES <= set(inspect(empty_engine).get_table_names())
    with empty_engine.connect() as connection:
        users = connection.exec_driver_sql("SELECT role FROM users").all()
    assert [row.role for row in users] == ["admin"]
