"""Test databases on a real PostgreSQL 16 (the CI service, or any local server).

DATABASE_URL points at a server the tests may create databases on. The tests never touch the
database it names: each run creates its own throwaway database (`supplier_iscan_test_<random>`)
and drops it at the end, so a developer's data is safe and parallel runs do not collide.
"""

import secrets
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 - registers every table on Base.metadata
from app.db import Base, to_sqlalchemy_url


@contextmanager
def temporary_database(server_url: str) -> Iterator[str]:
    """Create an empty database on the server of `server_url`; yield its URL; drop it."""
    name = f"supplier_iscan_test_{secrets.token_hex(6)}"
    url = make_url(to_sqlalchemy_url(server_url))
    admin = create_engine(url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with admin.connect() as connection:
            # `name` is generated above, never user input.
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        try:
            yield url.set(database=name).render_as_string(hide_password=False)
        finally:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


def truncate_all(engine: Engine) -> None:
    """Empty every table of the models, so that each test starts from a clean database."""
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
