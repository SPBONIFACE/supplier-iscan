"""POST /runs/{id}/fit and POST /runs/{id}/recommendations (openapi.yaml, tag `runs`). They only
check and queue; the worker drafts (`app.assessment.drafting`). Nothing here calls a model.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app import queue
from app.assessment.drafting import ASSESSMENT_JOB
from app.assessment.rules import NOT_ASSESSED
from app.assessment.stage import FIT_PROMPT, RECOMMENDATIONS_PROMPT
from app.buyer.values import run_criteria
from app.config import Settings
from app.db import DbSession
from app.limits.budget import used_up
from app.models import Job, ProfileRun, SupplierIdentity
from app.organisations.scope import OrganisationScope, OrganisationScoped

router = APIRouter(prefix="/runs", tags=["runs"])

ENTER_CRITERIA = "Enter your criteria to assess fit"
NOT_DRAFTED = "The assessment has not been drafted yet."
BUDGET_REACHED = "The run reached its cost budget; no further AI call is made for it."
PENDING_STATES = ("queued", "running")


class DraftingAccepted(BaseModel):
    """Mirrors components/schemas/DraftingAccepted."""

    model_config = ConfigDict(extra="forbid")

    part: Literal["fit", "recommendations"]
    status: Literal["queued"]


def pending_parts(db: DbSession, run_id: uuid.UUID) -> list[str]:
    """The parts whose drafting job is queued or running for the run."""
    rows = db.execute(
        select(Job.payload).where(Job.kind == ASSESSMENT_JOB, Job.state.in_(PENDING_STATES))
    )
    parts = {payload.get("part") for (payload,) in rows if payload.get("run_id") == str(run_id)}
    return [part for part in (FIT_PROMPT, RECOMMENDATIONS_PROMPT) if part in parts]


def _queue(
    db: DbSession, scope: OrganisationScope, run: ProfileRun, part: str, settings: Settings
) -> DraftingAccepted:
    identity = db.scalar(
        scope.select(SupplierIdentity).where(SupplierIdentity.id == run.identity_id)
    )
    if identity is not None and identity.natural_person:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NOT_ASSESSED)
    if part == FIT_PROMPT and not run_criteria(db, run.id):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=ENTER_CRITERIA)
    if used_up(db, run, settings.run_budget_eur):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=BUDGET_REACHED)
    if run.assessment_drafted_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NOT_DRAFTED)
    if part not in pending_parts(db, run.id):  # a second request while one is waiting adds none
        queue.enqueue(db, ASSESSMENT_JOB, {"run_id": str(run.id), "part": part})
        db.commit()
    return DraftingAccepted(part=part, status="queued")  # type: ignore[arg-type]


@router.post("/{id}/fit", status_code=status.HTTP_202_ACCEPTED, response_model=DraftingAccepted)
def draft_fit(
    id: str, scope: OrganisationScoped, db: DbSession, request: Request
) -> DraftingAccepted:
    run = scope.get(db, ProfileRun, id, for_update=True)  # the one 404 for another organisation
    return _queue(db, scope, run, FIT_PROMPT, request.app.state.settings)


@router.post(
    "/{id}/recommendations", status_code=status.HTTP_202_ACCEPTED, response_model=DraftingAccepted
)
def draft_recommendations(
    id: str, scope: OrganisationScoped, db: DbSession, request: Request
) -> DraftingAccepted:
    run = scope.get(db, ProfileRun, id, for_update=True)
    return _queue(db, scope, run, RECOMMENDATIONS_PROMPT, request.app.state.settings)
