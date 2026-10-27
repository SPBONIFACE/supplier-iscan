"""Alembic environment. Online mode only (migrations always run against a database)."""

import os

from alembic import context
from sqlalchemy import Connection

import app.models  # noqa: F401 - registers every table on Base.metadata
from app.db import Base, make_engine

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is not set")
    engine = make_engine(database_url)
    try:
        with engine.connect() as new_connection:
            _run(new_connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (SQL script) mode is not supported")
run_migrations_online()
