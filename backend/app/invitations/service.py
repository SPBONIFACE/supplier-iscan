"""Invitations (spec F7, Flow 2): single-use links that expire, and the seat limit.

The link carries a random 256-bit token; only its SHA-256 hash is stored (as for sessions), so a
copy of the database cannot be turned into a usable link.

Concurrency: accepting locks the invitation row, then the organisation row (`SELECT … FOR
UPDATE`), so that two acceptances of one invitation, or of two invitations for an organisation's
last seat, are serialised: exactly one succeeds.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.auth.sessions import hash_token, new_token, open_session
from app.config import Settings
from app.models import Invitation, Organisation, UsageEvent, User

# The same answer for an unknown, expired, revoked or used link, and for an email that meanwhile
# has an account: it says nothing about any account.
INVALID_INVITATION = "This invitation link is not valid. Ask your administrator for a new one."
SEAT_LIMIT_REACHED = "Seat limit reached."
EMAIL_HAS_ACCOUNT = "An account already exists for this email."
ALREADY_USED = "This invitation has already been used."

# Enough to catch a typo; the address is not verified (no email is sent).
_EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# new_token() is 43 characters; anything much longer is not one of ours.
_MAX_TOKEN_LENGTH = 128


class InvitationRefused(Exception):
    """The link cannot be used (404 InvalidInvitation)."""


class SeatLimitReached(Exception):
    """The organisation has as many members as its seat limit (409)."""


class EmailHasAccount(Exception):
    """An invitation for an email that already has an account (409)."""


class InvitationAlreadyUsed(Exception):
    """Revoking an invitation that was already accepted (409)."""


@dataclass(frozen=True)
class CreatedInvitation:
    invitation: Invitation
    link: str


@dataclass(frozen=True)
class AcceptedInvitation:
    user: User
    session_token: str


def is_valid_email(email: str) -> bool:
    return _EMAIL_PATTERN.fullmatch(email) is not None


def invitation_link(settings: Settings, token: str) -> str:
    """The frontend page for the token: the first allowed origin (the frontend's own origin)."""
    return f"{settings.allowed_origins[0].rstrip('/')}/invitations/{token}"


def count_members(db: Session, organisation_id: uuid.UUID) -> int:
    """Users of the organisation, every role included: they are what the seat limit counts."""
    return (
        db.scalar(
            select(func.count()).select_from(User).where(User.organisation_id == organisation_id)
        )
        or 0
    )


def _email_has_account(db: Session, email: str) -> bool:
    return db.scalar(select(User.id).where(User.email == email)) is not None


def create_invitation(
    db: Session, organisation: Organisation, email: str, settings: Settings, now: datetime
) -> CreatedInvitation:
    """Add an invitation (the caller commits). `email` is already normalised and valid."""
    if _email_has_account(db, email):
        raise EmailHasAccount
    token = new_token()
    invitation = Invitation(
        organisation_id=organisation.id,
        email=email,
        token_hash=hash_token(token),
        created_at=now,
        expires_at=now + settings.invitation_validity,
    )
    db.add(invitation)
    db.flush()
    return CreatedInvitation(invitation, invitation_link(settings, token))


def _usable(invitation: Invitation | None, now: datetime) -> Invitation:
    if (
        invitation is None
        or invitation.used_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= now
    ):
        raise InvitationRefused
    return invitation


def _find(db: Session, token: str, lock: bool) -> Invitation | None:
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        return None
    query = select(Invitation).where(Invitation.token_hash == hash_token(token))
    if lock:
        # populate_existing: read the row as it is once locked, not a copy from before the wait.
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def check_invitation(db: Session, token: str, now: datetime) -> tuple[Invitation, Organisation]:
    """The invitation and its organisation, or InvitationRefused."""
    invitation = _usable(_find(db, token, lock=False), now)
    if _email_has_account(db, invitation.email):
        raise InvitationRefused
    organisation = db.get_one(Organisation, invitation.organisation_id)
    return invitation, organisation


def accept_invitation(db: Session, token: str, password: str, now: datetime) -> AcceptedInvitation:
    """Create the member, mark the invitation used and open a session (the caller commits).

    `password` has already been checked against the configured minimum length.
    """
    # Cheap check first, so that an unknown link costs no password hashing; the hash is computed
    # before any row is locked, so that locks are held only briefly.
    check_invitation(db, token, now)
    db.rollback()
    password_hash = hash_password(password)

    invitation = _usable(_find(db, token, lock=True), now)
    organisation = db.scalars(
        select(Organisation)
        .where(Organisation.id == invitation.organisation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    if _email_has_account(db, invitation.email):
        raise InvitationRefused
    if (
        organisation.seat_limit is not None
        and count_members(db, organisation.id) >= organisation.seat_limit
    ):
        raise SeatLimitReached

    user = User(
        organisation_id=organisation.id,
        email=invitation.email,
        password_hash=password_hash,
        role="member",
        created_at=now,
        last_login_at=now,
    )
    db.add(user)
    invitation.used_at = now
    try:
        db.flush()
    except IntegrityError:
        # The same email accepted at the same moment through an invitation of another
        # organisation: the unique email constraint decides, and this one is refused.
        db.rollback()
        raise InvitationRefused from None

    session_token = open_session(db, user.id, now)
    # Accepting signs the person in: recorded like a login (spec F7, usage log).
    db.add(
        UsageEvent(kind="login", user_id=user.id, organisation_id=organisation.id, created_at=now)
    )
    return AcceptedInvitation(user, session_token)


def revoke_invitation(invitation: Invitation, now: datetime) -> None:
    """Revoke an unused invitation (the caller commits). Revoking twice changes nothing."""
    if invitation.used_at is not None:
        raise InvitationAlreadyUsed
    if invitation.revoked_at is None:
        invitation.revoked_at = now
