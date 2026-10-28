"""Invitation endpoints (openapi.yaml, tags `admin` and `invitations`; spec Flow 2, F7).

Administrator only (401 without a session, 403 for a member):

    POST   /admin/organisations/{id}/invitations   create; returns the link once
    DELETE /admin/invitations/{id}                 revoke an unused invitation

Public, the token being the credential:

    GET  /invitations/{token}          validity check
    POST /invitations/{token}/accept   set a password, join the organisation, get signed in
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select

from app.auth.dependencies import require_administrator
from app.auth.passwords import normalise_email
from app.auth.routes import CurrentUser
from app.auth.sessions import set_session_cookie
from app.db import DbSession, utc_now
from app.errors import InvalidField, not_found, parse_resource_id
from app.invitations import service
from app.models import Invitation, Organisation
from app.settings_dependency import CurrentSettings

logger = logging.getLogger(__name__)

admin_router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_administrator)]
)
public_router = APIRouter(prefix="/invitations", tags=["invitations"])


class InvitationCreate(BaseModel):
    """Mirrors components/schemas/InvitationCreate."""

    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)]


class CreatedInvitationOut(BaseModel):
    """Mirrors components/schemas/CreatedInvitation."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    organisation_id: uuid.UUID
    email: str
    expires_at: datetime
    link: str


class InvitationCheck(BaseModel):
    """Mirrors components/schemas/InvitationCheck."""

    model_config = ConfigDict(extra="forbid")

    email: str
    organisation_name: str
    expires_at: datetime


class InvitationAccept(BaseModel):
    """Mirrors components/schemas/InvitationAccept. The minimum length is configured."""

    model_config = ConfigDict(extra="forbid")

    # Not stripped: spaces are valid in a password.
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


def _refused() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=service.INVALID_INVITATION)


@admin_router.post(
    "/organisations/{id}/invitations",
    status_code=status.HTTP_201_CREATED,
    response_model=CreatedInvitationOut,
)
def create_invitation(
    id: str, body: InvitationCreate, db: DbSession, settings: CurrentSettings
) -> CreatedInvitationOut:
    organisation_id = parse_resource_id(id)
    organisation = db.scalar(select(Organisation).where(Organisation.id == organisation_id))
    if organisation is None:
        raise not_found()
    email = normalise_email(body.email)
    if not service.is_valid_email(email):
        raise InvalidField("email", "Email is not valid.")
    try:
        created = service.create_invitation(db, organisation, email, settings, utc_now())
    except service.EmailHasAccount:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=service.EMAIL_HAS_ACCOUNT) from None
    db.commit()
    invitation = created.invitation
    logger.info("Invitation %s created for organisation %s", invitation.id, organisation.id)
    return CreatedInvitationOut(
        id=invitation.id,
        organisation_id=invitation.organisation_id,
        email=invitation.email,
        expires_at=invitation.expires_at,
        link=created.link,
    )


@admin_router.delete(
    "/invitations/{id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def revoke_invitation(id: str, db: DbSession) -> Response:
    invitation_id = parse_resource_id(id)
    invitation = db.scalar(
        select(Invitation).where(Invitation.id == invitation_id).with_for_update()
    )
    if invitation is None:
        raise not_found()
    try:
        service.revoke_invitation(invitation, utc_now())
    except service.InvitationAlreadyUsed:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=service.ALREADY_USED) from None
    db.commit()
    logger.info("Invitation %s revoked", invitation.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@public_router.get("/{token}", response_model=InvitationCheck)
def check_invitation(token: str, db: DbSession) -> InvitationCheck:
    try:
        invitation, organisation = service.check_invitation(db, token, utc_now())
    except service.InvitationRefused:
        raise _refused() from None
    return InvitationCheck(
        email=invitation.email,
        organisation_name=organisation.name,
        expires_at=invitation.expires_at,
    )


@public_router.post("/{token}/accept", response_model=CurrentUser)
def accept_invitation(
    token: str,
    body: InvitationAccept,
    response: Response,
    db: DbSession,
    settings: CurrentSettings,
) -> CurrentUser:
    minimum = settings.password_min_length
    if len(body.password) < minimum:
        raise InvalidField("password", f"Password must be at least {minimum} characters.")
    try:
        accepted = service.accept_invitation(db, token, body.password, utc_now())
    except service.InvitationRefused:
        raise _refused() from None
    except service.SeatLimitReached:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=service.SEAT_LIMIT_REACHED) from None
    db.commit()
    user = accepted.user
    logger.info(
        "Invitation accepted: user %s joined organisation %s", user.id, user.organisation_id
    )

    set_session_cookie(response, accepted.session_token)
    return CurrentUser.model_validate(
        {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "organisation_id": user.organisation_id,
        }
    )
