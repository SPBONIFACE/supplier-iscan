"""Rows for tests, written through the application's own models and helpers."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password, normalise_email
from app.auth.sessions import SESSION_LIFETIME, hash_token, new_token
from app.db import utc_now
from app.models import Invitation, Organisation, User, UserSession

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
    engine: Engine,
    name: str = "Acme Buyers",
    status: str = "active",
    seat_limit: int | None = None,
    access_ends_at: datetime | None = None,
) -> uuid.UUID:
    with Session(engine) as db:
        organisation = Organisation(
            name=name, status=status, seat_limit=seat_limit, access_ends_at=access_ends_at
        )
        db.add(organisation)
        db.commit()
        return organisation.id


@dataclass(frozen=True)
class TestInvitation:
    __test__ = False  # not a pytest test class

    id: uuid.UUID
    token: str
    email: str
    organisation_id: uuid.UUID


def create_invitation(
    engine: Engine,
    organisation_id: uuid.UUID,
    email: str | None = None,
    expires_at: datetime | None = None,
    used_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> TestInvitation:
    """Insert an invitation row directly and return it with its link token."""
    token = new_token()
    email = normalise_email(email or f"invitee-{secrets.token_hex(4)}@example.test")
    now = utc_now()
    with Session(engine) as db:
        invitation = Invitation(
            organisation_id=organisation_id,
            email=email,
            token_hash=hash_token(token),
            created_at=now,
            expires_at=expires_at or now + timedelta(hours=1),
            used_at=used_at,
            revoked_at=revoked_at,
        )
        db.add(invitation)
        db.commit()
        return TestInvitation(invitation.id, token, email, organisation_id)


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
