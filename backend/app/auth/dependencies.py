"""The one way to protect an endpoint: depend on `require_session`.

    @router.get("/things")
    def list_things(principal: CurrentPrincipal) -> ...:

It answers 401 when the session cookie is missing, unknown (tampered), expired or revoked. Tests of
every protected endpoint call `tests.auth_support.assert_requires_session`.

Administrator-only endpoints depend on `AdministratorPrincipal` instead (or put
`require_administrator` in the router's dependencies): 401 without a valid session, then 403 for a
signed-in member.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.auth.sessions import SESSION_COOKIE_NAME, find_active_session
from app.db import DbSession, utc_now

AUTHENTICATION_REQUIRED = "Authentication required."
ADMINISTRATOR_REQUIRED = "Administrator access required."


@dataclass(frozen=True)
class Principal:
    """The signed-in user of the current request."""

    user_id: uuid.UUID
    email: str
    role: str
    organisation_id: uuid.UUID
    session_id: uuid.UUID


def _unauthorised() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=AUTHENTICATION_REQUIRED)


def session_token(request: Request) -> str:
    """The session cookie, checked before any database access."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise _unauthorised()
    return token


def require_session(token: Annotated[str, Depends(session_token)], db: DbSession) -> Principal:
    found = find_active_session(db, token, utc_now())
    if found is None:
        raise _unauthorised()
    user_session, user = found
    return Principal(
        user_id=user.id,
        email=user.email,
        role=user.role,
        organisation_id=user.organisation_id,
        session_id=user_session.id,
    )


# Type of an endpoint parameter that receives the signed-in user (401 when there is none).
CurrentPrincipal = Annotated[Principal, Depends(require_session)]


def require_administrator(principal: CurrentPrincipal) -> Principal:
    if principal.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ADMINISTRATOR_REQUIRED)
    return principal


# Type of an endpoint parameter that receives a signed-in administrator (401, then 403).
AdministratorPrincipal = Annotated[Principal, Depends(require_administrator)]
