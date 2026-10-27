"""Alembic migrations, run from code (startup, tests) or from the command line.

The migration scripts live in `app/migrations` so that they ship in the image (the Dockerfile copies
`app/` only); no `alembic.ini` is needed at run time.

Command line, from `backend/` with DATABASE_URL set:

    uv run alembic upgrade head
    uv run alembic revision --autogenerate -m "short description"

A new migration's `down_revision` must be the current head: the test suite fails when there is
more than one head (two branches each added a migration) or when the models and the migrations
disagree.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection

MIGRATIONS_PATH = Path(__file__).resolve().parent / "migrations"


def alembic_config(connection: Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_PATH))
    if connection is not None:
        # Read by env.py: run on this connection instead of opening one from DATABASE_URL.
        config.attributes["connection"] = connection
    return config


def upgrade_to_head(connection: Connection) -> None:
    command.upgrade(alembic_config(connection), "head")
