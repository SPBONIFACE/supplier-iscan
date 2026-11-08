"""Database layer: SQLAlchemy 2.0 (sync) on psycopg 3, one engine per application.

How to use it in an endpoint:

    from app.db import DbSession

    @router.get("/things")
    def list_things(db: DbSession) -> ...:
        ...
        db.commit()  # write endpoints commit explicitly

A request gets one session (FastAPI caches the dependency per request); it is closed at the end of
the request, and anything not committed is rolled back. When the database is unreachable, the
`OperationalError` raised by SQLAlchemy is turned into a plain 503 by `app.errors`.

Schema changes go through Alembic (`app/migrations`, see `app.migrate`).
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import DeclarativeBase, Session

# Short enough that a request fails fast when the database is down, long enough for a cold
# serverless database to wake up.
DATABASE_CONNECT_TIMEOUT_SECONDS = 5
# The longest one statement may run; the setting DATABASE_STATEMENT_TIMEOUT_SECONDS overrides it.
DEFAULT_STATEMENT_TIMEOUT_SECONDS = 30

# Stable constraint names, so that migrations can refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class of every model. Its metadata is the target of Alembic autogenerate."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class DatabaseUnavailable(Exception):
    """The database is not configured, or its URL cannot be used. Answered with a 503."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_sqlalchemy_url(database_url: str) -> str:
    """DATABASE_URL uses the libpq form (`postgresql://…`); SQLAlchemy needs the driver name."""
    for prefix in ("postgresql://", "postgres://"):
        if database_url.startswith(prefix):
            return "postgresql+psycopg://" + database_url.removeprefix(prefix)
    return database_url


def make_engine(
    database_url: str, statement_timeout_seconds: int = DEFAULT_STATEMENT_TIMEOUT_SECONDS
) -> Engine:
    return create_engine(
        to_sqlalchemy_url(database_url),
        pool_pre_ping=True,
        # Never put bound parameters (password hashes, token hashes, emails) in logs or in the
        # text of exceptions.
        hide_parameters=True,
        connect_args={
            "connect_timeout": DATABASE_CONNECT_TIMEOUT_SECONDS,
            # A statement that does not finish is cancelled by the server (an OperationalError,
            # answered with a 503 / a paused run), so a stuck database never hangs a request.
            "options": f"-c statement_timeout={statement_timeout_seconds * 1000}",
        },
    )


class Database:
    """The application's engine, created on first use so that the API starts without a database."""

    def __init__(
        self,
        database_url: str | None,
        engine: Engine | None = None,
        statement_timeout_seconds: int = DEFAULT_STATEMENT_TIMEOUT_SECONDS,
    ) -> None:
        self._database_url = database_url
        self._engine = engine
        self._statement_timeout_seconds = statement_timeout_seconds

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            if not self._database_url:
                raise DatabaseUnavailable("DATABASE_URL is not set")
            try:
                self._engine = make_engine(self._database_url, self._statement_timeout_seconds)
            except ArgumentError:
                # The message would contain the URL: drop it.
                raise DatabaseUnavailable("DATABASE_URL cannot be parsed") from None
        return self._engine

    def session(self) -> Session:
        return Session(self.engine, expire_on_commit=False)

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()


def get_db_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed (rolled back if needed) at the end."""
    database: Database = request.app.state.database
    with database.session() as session:
        yield session


# Type of an endpoint parameter that receives the request's database session.
DbSession = Annotated[Session, Depends(get_db_session)]
