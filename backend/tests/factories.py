"""Rows for tests, written through the application's own models and helpers."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password, normalise_email
from app.auth.sessions import SESSION_LIFETIME, hash_token, new_token
from app.db import utc_now
from app.models import Organisation, User, UserSession

DEFAULT_PASSWORD = "correct horse battery staple"  # noqa: S105 - test credential


@dataclass(frozen=True)
class TestUser:
    __test__ = False  # not a pytest test class

    id: uuid.UUID
    email: str
    password: str
    role: str
    organisation_id: uuid.UUID


def create_organisation(
    engine: Engine, name: str = "Acme Buyers", status: str = "active"
) -> uuid.UUID:
    with Session(engine) as db:
        organisation = Organisation(name=name, status=status)
        db.add(organisation)
        db.commit()
        return organisation.id


def create_user(
    engine: Engine,
    email: str | None = None,
    password: str = DEFAULT_PASSWORD,
    role: str = "member",
    organisation_id: uuid.UUID | None = None,
) -> TestUser:
    email = normalise_email(email or f"member-{secrets.token_hex(4)}@example.test")
    organisation_id = organisation_id or create_organisation(engine)
    with Session(engine) as db:
        user = User(
            organisation_id=organisation_id,
            email=email,
            password_hash=hash_password(password),
            role=role,
        )
        db.add(user)
        db.commit()
        return TestUser(user.id, email, password, role, organisation_id)


def create_session(
    engine: Engine,
    user_id: uuid.UUID,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> str:
    """Insert a session row directly and return its cookie token."""
    token = new_token()
    now = utc_now()
    with Session(engine) as db:
        db.add(
            UserSession(
                user_id=user_id,
                token_hash=hash_token(token),
                created_at=now,
                expires_at=expires_at or now + SESSION_LIFETIME,
                revoked_at=revoked_at,
            )
        )
        db.commit()
    return token
