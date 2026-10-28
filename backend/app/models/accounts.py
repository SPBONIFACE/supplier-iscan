"""Organisations, users and their sessions (spec, Data model & ownership)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ORGANISATION_STATUSES = ("pending_activation", "active", "acceptance_renewal_required")
USER_ROLES = ("admin", "member")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _positive_or_null(column: str) -> str:
    return f"{column} IS NULL OR {column} > 0"


class Organisation(Base):
    """An organisation and its limits. A null limit means unlimited (limits are off by default).

    `access_period_days` is the length of the access period; it starts at activation, which sets
    `access_ends_at` (at creation on a self-hosted instance, where activation is skipped).
    """

    __tablename__ = "organisations"
    __table_args__ = (
        CheckConstraint(_in("status", ORGANISATION_STATUSES), name="status"),
        CheckConstraint(_positive_or_null("seat_limit"), name="seat_limit_positive"),
        CheckConstraint(_positive_or_null("profile_quota"), name="profile_quota_positive"),
        CheckConstraint(
            _positive_or_null("access_period_days"), name="access_period_days_positive"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40))
    seat_limit: Mapped[int | None] = mapped_column(Integer)
    profile_quota: Mapped[int | None] = mapped_column(Integer)
    access_period_days: Mapped[int | None] = mapped_column(Integer)
    access_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("role", USER_ROLES), name="role"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"), index=True)
    # Stored lower-cased and trimmed (see app.auth.passwords.normalise_email).
    email: Mapped[str] = mapped_column(String(320), unique=True)
    # Argon2id hash only; the password itself is never stored.
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    """A sign-in session, stored on the server so that logout really ends it.

    Only the SHA-256 hash of the cookie token is stored (owner decision, 27 Oct 2026).
    """

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
