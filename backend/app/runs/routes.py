"""/runs (openapi.yaml, tag `runs`). Endpoints only queue, flag or read; no stage executes here.

An administrator is scoped like any member (their own organisation) but gets run metadata only:
`supplier_name` is null for them (spec, Data model & ownership).
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app import queue
from app.db import DbSession, utc_now
from app.errors import not_found
from app.models import ProfileRun, SupplierIdentity, UsageEvent
from app.models.runs import FINISHED_STATUSES
from app.organisations.scope import OrganisationScope, OrganisationScoped
from app.providers.usage import run_usage_totals
from app.runs.executor import RUN_JOB

router = APIRouter(prefix="/runs", tags=["runs"])

LIST_LIMIT = 100
ALREADY_FINISHED = "The run has already finished."
NOT_PAUSED = "The run is not paused."


class RunStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_id: uuid.UUID


class RunRoleModelOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["retrieval", "structuring"]
    config_id: str
    provider: str
    model_id: str


class RunUsageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calls: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    tool_calls: int
    cost: str
    roles: list[RunRoleModelOut]


class RunOut(BaseModel):
    """Mirrors components/schemas/Run."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    identity_id: uuid.UUID
    supplier_name: str | None
    status: str
    stage: str
    stop_requested: bool
    counts_against_quota: bool
    pause_dependency: str | None
    pause_reason: str | None
    error: str | None
    profile_definition_hash: str | None
    prompt_set_hash: str | None
    usage: RunUsageOut
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RunOut]


def _run_out(
    db: DbSession, scope: OrganisationScope, run: ProfileRun, supplier_name: str | None
) -> RunOut:
    totals = run_usage_totals(db, scope.organisation_id, run.id)
    roles = [
        {"role": role, "config_id": m.config_id, "provider": m.provider, "model_id": m.model_id}
        for role, models in totals.roles.items()
        for m in models
    ]
    return RunOut.model_validate(
        {
            "id": run.id,
            "identity_id": run.identity_id,
            # Run metadata only for an administrator, never the supplier name.
            "supplier_name": None if scope.principal.role == "admin" else supplier_name,
            "status": run.status,
            "stage": run.stage,
            "stop_requested": run.stop_requested,
            "counts_against_quota": run.counts_against_quota,
            "pause_dependency": run.pause_dependency,
            "pause_reason": run.pause_reason,
            "error": run.error,
            "profile_definition_hash": run.profile_definition_hash,
            "prompt_set_hash": run.prompt_set_hash,
            "usage": {
                "calls": totals.calls,
                "input_tokens": totals.input_tokens,
                "output_tokens": totals.output_tokens,
                "reasoning_tokens": totals.reasoning_tokens,
                "tool_calls": totals.tool_calls,
                "cost": format(totals.cost, "f"),
                "roles": roles,
            },
            "created_at": run.created_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }
    )


def _one(db: DbSession, scope: OrganisationScope, run: ProfileRun) -> RunOut:
    name = db.scalar(scope.select(SupplierIdentity).where(SupplierIdentity.id == run.identity_id))
    return _run_out(db, scope, run, name.legal_name if name else None)


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=RunOut)
def start_run(body: RunStart, scope: OrganisationScoped, db: DbSession) -> RunOut:
    identity = scope.get(db, SupplierIdentity, body.identity_id)
    if identity.confirmed_at is None:
        # Same answer as an unknown identity: only a confirmed identity starts a run.
        raise not_found()
    run = scope.new(ProfileRun, identity_id=identity.id, created_by=scope.principal.user_id)
    db.add(run)
    db.flush()
    queue.enqueue(db, RUN_JOB, {"run_id": str(run.id)})
    db.add(
        UsageEvent(
            kind="run", user_id=scope.principal.user_id, organisation_id=scope.organisation_id
        )
    )
    db.commit()
    db.refresh(run)
    return _run_out(db, scope, run, identity.legal_name)


@router.get("", response_model=RunListOut)
def list_runs(scope: OrganisationScoped, db: DbSession) -> RunListOut:
    runs = db.scalars(
        scope.select(ProfileRun).order_by(ProfileRun.created_at.desc()).limit(LIST_LIMIT)
    ).all()
    rows = db.execute(
        select(SupplierIdentity.id, SupplierIdentity.legal_name).where(
            SupplierIdentity.organisation_id == scope.organisation_id,
            SupplierIdentity.id.in_({run.identity_id for run in runs}),
        )
    )
    names = {identity_id: name for identity_id, name in rows}
    return RunListOut(items=[_run_out(db, scope, run, names.get(run.identity_id)) for run in runs])


@router.get("/{id}", response_model=RunOut)
def get_run(id: str, scope: OrganisationScoped, db: DbSession) -> RunOut:
    return _one(db, scope, scope.get(db, ProfileRun, id))


@router.post("/{id}/stop", response_model=RunOut)
def stop_run(id: str, scope: OrganisationScoped, db: DbSession) -> RunOut:
    run = scope.get(db, ProfileRun, id, for_update=True)
    if run.status in FINISHED_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=ALREADY_FINISHED)
    run.stop_requested = True
    if run.status in ("queued", "paused"):
        # Nothing is executing: it ends now. A queued run's job finds it stopped and does nothing.
        run.status = "stopped"
        run.finished_at = utc_now()
    db.commit()
    return _one(db, scope, run)


@router.post("/{id}/resume", status_code=status.HTTP_202_ACCEPTED, response_model=RunOut)
def resume_run(id: str, scope: OrganisationScoped, db: DbSession) -> RunOut:
    run = scope.get(db, ProfileRun, id, for_update=True)
    if run.status != "paused":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NOT_PAUSED)
    run.status = "queued"
    run.pause_dependency = None
    run.pause_reason = None
    run.counts_against_quota = True
    queue.enqueue(db, RUN_JOB, {"run_id": str(run.id)})
    db.commit()
    return _one(db, scope, run)
