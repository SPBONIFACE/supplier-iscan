"""GET /organisation (openapi.yaml, tag `organisation`): the signed-in member's own organisation.

There is no organisation id to pass: the organisation is the session's. The remaining profile
quota comes with #29.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.db import DbSession
from app.errors import not_found
from app.models import Organisation
from app.organisations.scope import OrganisationScoped

router = APIRouter(prefix="/organisation", tags=["organisation"])


class MemberOrganisationOut(BaseModel):
    """Mirrors components/schemas/MemberOrganisation."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["pending_activation", "active", "acceptance_renewal_required"]
    seat_limit: int | None
    profile_quota: int | None
    access_ends_at: datetime | None


@router.get("", response_model=MemberOrganisationOut)
def get_own_organisation(scope: OrganisationScoped, db: DbSession) -> MemberOrganisationOut:
    organisation = db.scalar(select(Organisation).where(Organisation.id == scope.organisation_id))
    if organisation is None:  # a user always has an organisation; kept as the generic 404
        raise not_found()
    return MemberOrganisationOut.model_validate(
        {
            "name": organisation.name,
            "status": organisation.status,
            "seat_limit": organisation.seat_limit,
            "profile_quota": organisation.profile_quota,
            "access_ends_at": organisation.access_ends_at,
        }
    )
