"""Server-side sessions: an opaque random token in the cookie, its SHA-256 hash in the database.

The token carries 256 bits of randomness, so a plain SHA-256 is enough: the stored hash cannot be
turned back into a usable cookie, and no signing secret is needed.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, UserSession

SESSION_COOKIE_NAME = "supplier_iscan_session"
SESSION_LIFETIME = timedelta(hours=12)
# token_urlsafe(32) is 43 characters; anything much longer is not one of ours.
_MAX_TOKEN_LENGTH = 128


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def open_session(db: Session, user_id: uuid.UUID, now: datetime) -> str:
    """Add a session for the user (the caller commits) and return the token for the cookie."""
    token = new_token()
    db.add(
        UserSession(
            user_id=user_id,
            token_hash=hash_token(token),
            created_at=now,
            expires_at=now + SESSION_LIFETIME,
        )
    )
    return token


def find_active_session(db: Session, token: str, now: datetime) -> tuple[UserSession, User] | None:
    """The session and user for this token, or None if unknown, expired or revoked."""
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        return None
    row = db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.token_hash == hash_token(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
    ).one_or_none()
    if row is None:
        return None
    return row[0], row[1]


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax"
    )
