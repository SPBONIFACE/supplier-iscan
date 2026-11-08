"""Health check: is the API up, can it reach its database, and which provider keys are missing?"""

import logging
from collections.abc import Callable
from typing import Literal

import psycopg
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# Short enough that GET /health answers quickly when the database is down.
DATABASE_CONNECT_TIMEOUT_SECONDS = 2

DatabaseCheck = Callable[[], bool]


class HealthStatus(BaseModel):
    """Mirrors components/schemas/HealthStatus in openapi.yaml."""

    model_config = ConfigDict(extra="forbid")

    api: Literal["available"]
    database: Literal["available", "unavailable"]
    # Names of the provider key settings the selected configurations need and lack (#11).
    missing_settings: list[str]


def make_database_check(database_url: str | None) -> DatabaseCheck:
    """Return a function that reports whether the database answers `SELECT 1`."""

    def check() -> bool:
        if not database_url:
            logger.warning("Database health check skipped: DATABASE_URL is not set")
            return False
        try:
            with psycopg.connect(
                database_url,
                connect_timeout=DATABASE_CONNECT_TIMEOUT_SECONDS,
                options=f"-c statement_timeout={DATABASE_CONNECT_TIMEOUT_SECONDS * 1000}",
            ) as connection:
                connection.execute("SELECT 1")
        except Exception as error:  # noqa: BLE001 - any failure means "unavailable"
            # Log the error type only: the message can contain the connection string.
            logger.warning("Database health check failed: %s", type(error).__name__)
            return False
        return True

    return check
