"""Administrator endpoints for organisations (openapi.yaml, tag `admin`; spec Flow 2, F7).

    POST  /admin/organisations       create, with its limits
    GET   /admin/organisations       list
    PATCH /admin/organisations/{id}  extend the access (a later access_ends_at)

Every endpoint is administrator-only: 401 without a session, 403 for a member.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select

from app.auth.dependencies import require_administrator
from app.config import Settings
from app.db import DbSession, utc_now
from app.errors import InvalidField, not_found, parse_resource_id
from app.invitations.service import count_members
from app.models import Organisation, User
from app.settings_dependency import CurrentSettings

logger = logging.getLogger(__name__)

# Technical bounds only (PostgreSQL integer; date arithmetic stays in range), not product terms.
MAX_LIMIT = 2_147_483_647
MAX_ACCESS_PERIOD_DAYS = 36_500

router = APIRouter(
    prefix="/admin/organisations",
    tags=["admin"],
    dependencies=[Depends(require_administrator)],
)

Limit = Annotated[int | None, Field(strict=True, ge=1, le=MAX_LIMIT)]


class OrganisationCreate(BaseModel):
    """Mirrors components/schemas/OrganisationCreate. A limit left empty means unlimited."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    seat_limit: Limit = None
    profile_quota: Limit = None
    access_period_days: Annotated[
        int | None, Field(strict=True, ge=1, le=MAX_ACCESS_PERIOD_DAYS)
    ] = None


class OrganisationAccessUpdate(BaseModel):
    """Mirrors components/schemas/OrganisationAccessUpdate."""

    model_config = ConfigDict(extra="forbid")

    access_ends_at: AwareDatetime


class OrganisationOut(BaseModel):
    """Mirrors components/schemas/Organisation."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    name: str
    status: Literal["pending_activation", "active", "acceptance_renewal_required"]
    seat_limit: int | None
    profile_quota: int | None
    access_period_days: int | None
    access_ends_at: datetime | None
    member_count: int
    created_at: datetime


class OrganisationList(BaseModel):
    """Mirrors components/schemas/OrganisationList."""

    model_config = ConfigDict(extra="forbid")

    organisations: list[OrganisationOut]


def _out(organisation: Organisation, member_count: int) -> OrganisationOut:
    return OrganisationOut.model_validate(
        {
            "id": organisation.id,
            "name": organisation.name,
            "status": organisation.status,
            "seat_limit": organisation.seat_limit,
            "profile_quota": organisation.profile_quota,
            "access_period_days": organisation.access_period_days,
            "access_ends_at": organisation.access_ends_at,
            "member_count": member_count,
            "created_at": organisation.created_at,
        }
    )


def initial_status(settings: Settings) -> str:
    # Self-hosted: activation is skipped (#42; owner decision, 27 Oct 2026).
    return "active" if settings.organisations_skip_activation else "pending_activation"


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrganisationOut)
def create_organisation(
    body: OrganisationCreate, db: DbSession, settings: CurrentSettings
) -> OrganisationOut:
    now = utc_now()
    organisation_status = initial_status(settings)
    # The access period starts at activation: now on a self-hosted instance, later (#42) otherwise.
    access_ends_at = (
        now + timedelta(days=body.access_period_days)
        if organisation_status == "active" and body.access_period_days is not None
        else None
    )
    organisation = Organisation(
        name=body.name,
        status=organisation_status,
        seat_limit=body.seat_limit,
        profile_quota=body.profile_quota,
        access_period_days=body.access_period_days,
        access_ends_at=access_ends_at,
        created_at=now,
    )
    db.add(organisation)
    db.commit()
    logger.info("Organisation %s created (%s)", organisation.id, organisation_status)
    return _out(organisation, 0)


@router.get("", response_model=OrganisationList)
def list_organisations(db: DbSession) -> OrganisationList:
    members = (
        select(User.organisation_id, func.count().label("member_count"))
        .group_by(User.organisation_id)
        .subquery()
    )
    rows = db.execute(
        select(Organisation, func.coalesce(members.c.member_count, 0))
        .outerjoin(members, members.c.organisation_id == Organisation.id)
        .order_by(Organisation.created_at, Organisation.id)
    ).all()
    return OrganisationList(organisations=[_out(row[0], row[1]) for row in rows])


@router.patch("/{id}", response_model=OrganisationOut)
def extend_organisation_access(
    id: str, body: OrganisationAccessUpdate, db: DbSession
) -> OrganisationOut:
    organisation_id = parse_resource_id(id)
    organisation = db.scalar(
        select(Organisation).where(Organisation.id == organisation_id).with_for_update()
    )
    if organisation is None:
        raise not_found()

    new_end = body.access_ends_at
    if new_end <= utc_now():
        raise InvalidField("access_ends_at", "Access ends at must be in the future.")
    if organisation.access_ends_at is not None and new_end <= organisation.access_ends_at:
        raise InvalidField(
            "access_ends_at", "Access ends at must be later than the current end of access."
        )

    organisation.access_ends_at = new_end
    db.commit()
    logger.info("Access of organisation %s extended", organisation.id)
    return _out(organisation, count_members(db, organisation.id))
