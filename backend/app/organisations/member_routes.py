"""GET /organisation (openapi.yaml, tag `organisation`): the signed-in member's own organisation.

There is no organisation id to pass: the organisation is the session's. It also carries the
remaining profile quota and the reason a new run would be refused (no spend amount); for an
administrator of a hosted instance that reason is `members_only` (#203).
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.db import DbSession
from app.errors import not_found
from app.models import Organisation
from app.organisations.scope import MEMBERS_ONLY_REASON, OrganisationScoped, content_hidden_from
from app.runs.refusal import RefusalReason, profiles_remaining, run_refusal_reason

router = APIRouter(prefix="/organisation", tags=["organisation"])


class MemberOrganisationOut(BaseModel):
    """Mirrors components/schemas/MemberOrganisation."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["pending_activation", "active", "acceptance_renewal_required"]
    seat_limit: int | None
    profile_quota: int | None
    profiles_remaining: int | None
    run_refusal_reason: RefusalReason | Literal["members_only"] | None
    access_ends_at: datetime | None
    comparison_max_profiles: int


@router.get("", response_model=MemberOrganisationOut)
def get_own_organisation(
    scope: OrganisationScoped, db: DbSession, request: Request
) -> MemberOrganisationOut:
    settings = request.app.state.settings
    organisation = db.scalar(select(Organisation).where(Organisation.id == scope.organisation_id))
    if organisation is None:  # a user always has an organisation; kept as the generic 404
        raise not_found()
    return MemberOrganisationOut.model_validate(
        {
            "name": organisation.name,
            "status": organisation.status,
            "seat_limit": organisation.seat_limit,
            "profile_quota": organisation.profile_quota,
            "profiles_remaining": profiles_remaining(db, organisation),
            # A hosted administrator starts no run: they test from a member account (#203).
            "run_refusal_reason": (
                MEMBERS_ONLY_REASON
                if content_hidden_from(scope.principal, settings)
                else run_refusal_reason(db, organisation, settings)
            ),
            "access_ends_at": organisation.access_ends_at,
            "comparison_max_profiles": settings.comparison_max_profiles,
        }
    )
