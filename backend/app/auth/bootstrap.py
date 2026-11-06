"""First start: the single local administrator and the default organisation (spec, Flow 4).

Runs at every startup, after the migrations, and does something only when the database has no
user. The email and initial password come from ADMIN_EMAIL and ADMIN_PASSWORD; nothing is
generated, and the password is never logged.
"""

import logging

from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password, normalise_email
from app.config import ADMIN_EMAIL, ADMIN_PASSWORD, ConfigurationError, Settings
from app.migrate import upgrade_to_head
from app.models import Organisation, User

logger = logging.getLogger(__name__)

DEFAULT_ORGANISATION_NAME = "Default organisation"

# Serialises startup across API instances (PostgreSQL advisory lock), so that two instances
# starting together neither migrate twice nor create two administrators.
_STARTUP_LOCK_KEY = 0x5157_4E01


def ensure_local_administrator(db: Session, settings: Settings) -> bool:
    """Create the administrator and the default organisation if there is no user yet.

    Returns True when they were created. Raises ConfigurationError naming any missing setting.
    """
    if db.scalar(select(func.count()).select_from(User)):
        return False

    email, password = settings.admin_email, settings.admin_password
    if not email or not password:
        missing = [
            name for name, value in ((ADMIN_EMAIL, email), (ADMIN_PASSWORD, password)) if not value
        ]
        raise ConfigurationError(
            f"Cannot create the local administrator on first start: set {' and '.join(missing)}"
        )

    organisation = Organisation(name=DEFAULT_ORGANISATION_NAME, status="active")
    db.add(organisation)
    db.flush()
    db.add(
        User(
            organisation_id=organisation.id,
            email=normalise_email(email),
            password_hash=hash_password(password),
            role="admin",
        )
    )
    db.commit()
    logger.info(
        "Local administrator created from %s and %s, in the organisation %r",
        ADMIN_EMAIL,
        ADMIN_PASSWORD,
        DEFAULT_ORGANISATION_NAME,
    )
    return True


def prepare_database(engine: Engine, settings: Settings) -> None:
    """Startup: apply the migrations, then create the local administrator if needed."""
    with engine.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _STARTUP_LOCK_KEY})
        connection.commit()
        try:
            # A migration may run long (an index build, a backfill): no statement timeout for it,
            # whatever DATABASE_STATEMENT_TIMEOUT_SECONDS says for requests.
            connection.execute(text("SET statement_timeout = 0"))
            upgrade_to_head(connection)
            connection.commit()
            with Session(engine, expire_on_commit=False) as db:
                ensure_local_administrator(db, settings)
        finally:
            connection.execute(text("RESET statement_timeout"))
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _STARTUP_LOCK_KEY})
            connection.commit()
