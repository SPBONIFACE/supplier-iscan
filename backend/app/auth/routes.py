"""POST /auth/login, POST /auth/logout, GET /auth/me (openapi.yaml, tag `auth`)."""

import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select, update

from app.auth.dependencies import CurrentPrincipal
from app.auth.passwords import (
    hash_password,
    needs_rehash,
    normalise_email,
    spend_verification_time,
    verify_password,
)
from app.auth.sessions import clear_session_cookie, open_session, set_session_cookie
from app.db import DbSession, utc_now
from app.models import UsageEvent, User, UserSession

logger = logging.getLogger(__name__)

# Same answer for a wrong password and an unknown email: no account enumeration.
INVALID_CREDENTIALS = "Incorrect email or password."

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Mirrors components/schemas/LoginRequest."""

    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=320)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class CurrentUser(BaseModel):
    """Mirrors components/schemas/CurrentUser."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    email: str
    role: Literal["admin", "member"]
    organisation_id: uuid.UUID


def _current_user(
    user_id: uuid.UUID, email: str, role: str, organisation_id: uuid.UUID
) -> CurrentUser:
    return CurrentUser.model_validate(
        {"id": user_id, "email": email, "role": role, "organisation_id": organisation_id}
    )


@router.post("/login", response_model=CurrentUser)
def login(body: LoginRequest, response: Response, db: DbSession) -> CurrentUser:
    now = utc_now()
    user = db.scalar(select(User).where(User.email == normalise_email(body.email)))

    if user is None or not verify_password(user.password_hash, body.password):
        if user is None:
            spend_verification_time(body.password)
        db.add(
            UsageEvent(
                kind="login_failed",
                user_id=user.id if user else None,
                organisation_id=user.organisation_id if user else None,
                created_at=now,
            )
        )
        db.commit()
        logger.info("Login failed")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS)

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = now
    token = open_session(db, user.id, now)
    db.add(
        UsageEvent(
            kind="login", user_id=user.id, organisation_id=user.organisation_id, created_at=now
        )
    )
    db.commit()
    logger.info("Login succeeded for user %s", user.id)

    set_session_cookie(response, token)
    return _current_user(user.id, user.email, user.role, user.organisation_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def logout(principal: CurrentPrincipal, db: DbSession) -> Response:
    db.execute(
        update(UserSession)
        .where(UserSession.id == principal.session_id)
        .values(revoked_at=utc_now())
    )
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


@router.get("/me", response_model=CurrentUser)
def get_current_user(principal: CurrentPrincipal) -> CurrentUser:
    return _current_user(
        principal.user_id, principal.email, principal.role, principal.organisation_id
    )
