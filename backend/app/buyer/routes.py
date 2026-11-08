"""The member's inputs for a run (openapi.yaml, tag `runs`): fit criteria, buyer context and the
free text of `buyer` fields. Each write names the version it is based on; an outdated version is
refused with 409 and the value stored now, so that no edit is silently lost. The run row is locked
for the write, so two members saving at once are told apart. Nothing here calls a model.
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.buyer.values import (
    Intent,
    Relationship,
    StoredContext,
    dump_context,
    dump_criteria,
    load_context_text,
    load_criteria_text,
    stored,
)
from app.config import Settings
from app.db import DbSession, utc_now
from app.errors import InvalidField
from app.models import BuyerInput, ProfileRun
from app.models.buyer import BUYER_CONTEXT, FIT_CRITERIA, RESERVED_FIELDS
from app.organisations.scope import OrganisationScope, OrganisationScoped
from app.profile_definition import ProfileDefinition
from app.runs.routes import user_emails

router = APIRouter(prefix="/runs", tags=["runs"])

CONFLICT = "Someone saved a newer version. Review it before saving again."


class CriteriaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[str] = Field(max_length=100)
    version: int = Field(ge=0)


class CriteriaOut(BaseModel):
    """Mirrors components/schemas/Criteria."""

    model_config = ConfigDict(extra="forbid")

    criteria: list[str]
    version: int
    updated_by: uuid.UUID | None
    updated_by_email: str | None
    updated_at: datetime


class BuyerContextUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship: Relationship
    current_share_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    contract_end_date: date | None = None
    strategic_intent: list[Intent] = Field(default_factory=list, max_length=4)
    notes: str | None = None
    version: int = Field(ge=0)


class BuyerContextOut(BaseModel):
    """Mirrors components/schemas/BuyerContext."""

    model_config = ConfigDict(extra="forbid")

    relationship: Literal["incumbent", "new"]
    current_share_pct: float | None
    contract_end_date: date | None
    strategic_intent: list[Intent]
    notes: str | None
    version: int
    updated_by: uuid.UUID | None
    updated_by_email: str | None
    updated_at: datetime


class BuyerInputUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    version: int = Field(ge=0)


class BuyerInputOut(BaseModel):
    """Mirrors components/schemas/BuyerInput."""

    model_config = ConfigDict(extra="forbid")

    field: str
    text: str
    version: int
    updated_by: uuid.UUID | None
    updated_by_email: str | None
    updated_at: datetime


class BuyerInputsOut(BaseModel):
    """Mirrors components/schemas/BuyerInputs."""

    model_config = ConfigDict(extra="forbid")

    criteria: CriteriaOut | None
    buyer_context: BuyerContextOut | None
    inputs: list[BuyerInputOut]


def _email(db: DbSession, scope: OrganisationScope, row: BuyerInput) -> str | None:
    """The email of the member who saved `row`, within the caller's organisation."""
    return user_emails(db, scope, {row.updated_by}).get(row.updated_by) if row.updated_by else None


def criteria_out(row: BuyerInput, email: str | None) -> CriteriaOut:
    return CriteriaOut(
        criteria=load_criteria_text(row.text),
        version=row.version,
        updated_by=row.updated_by,
        updated_by_email=email,
        updated_at=row.updated_at,
    )


def context_out(row: BuyerInput, email: str | None) -> BuyerContextOut:
    value = load_context_text(row.text)
    return BuyerContextOut(
        relationship=value.relationship,
        current_share_pct=value.current_share_pct,
        contract_end_date=value.contract_end_date,
        strategic_intent=value.strategic_intent,
        notes=value.notes,
        version=row.version,
        updated_by=row.updated_by,
        updated_by_email=email,
        updated_at=row.updated_at,
    )


def input_out(row: BuyerInput, email: str | None) -> BuyerInputOut:
    return BuyerInputOut(
        field=row.field,
        text=row.text,
        version=row.version,
        updated_by=row.updated_by,
        updated_by_email=email,
        updated_at=row.updated_at,
    )


def _conflict(current: BaseModel | None) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "detail": CONFLICT,
            "current": current.model_dump(mode="json") if current is not None else None,
        },
    )


def _write(
    db: DbSession,
    scope: OrganisationScope,
    run: ProfileRun,
    field: str,
    text: str,
    version: int,
) -> BuyerInput | None:
    """Store `text` when `version` is the stored version (0 when none); None on a conflict. The
    caller holds the lock on the run."""
    row = stored(db, run.id, field)
    if (row.version if row is not None else 0) != version:
        return None
    if row is None:
        row = scope.new(BuyerInput, run_id=run.id, field=field, version=1)
        db.add(row)
    else:
        row.version += 1
    row.text = text
    row.updated_by = scope.principal.user_id
    row.updated_at = utc_now()
    db.commit()
    db.refresh(row)
    return row


@router.put("/{id}/criteria", response_model=CriteriaOut)
def put_criteria(
    id: str, body: CriteriaUpdate, scope: OrganisationScoped, db: DbSession, request: Request
) -> Any:
    run = scope.get(db, ProfileRun, id, for_update=True)  # the one 404 for another organisation
    settings: Settings = request.app.state.settings
    criteria = [item.strip() for item in body.criteria]
    if any(not item for item in criteria):
        raise InvalidField("criteria", "A criterion is not empty.")
    if sum(len(item) for item in criteria) > settings.criteria_max_chars:
        raise InvalidField("criteria", "Criteria are too long.")
    row = _write(db, scope, run, FIT_CRITERIA, dump_criteria(criteria), body.version)
    if row is None:
        current = stored(db, run.id, FIT_CRITERIA)
        return _conflict(
            criteria_out(current, _email(db, scope, current)) if current is not None else None
        )
    return criteria_out(row, _email(db, scope, row))


@router.put("/{id}/buyer-context", response_model=BuyerContextOut)
def put_buyer_context(
    id: str, body: BuyerContextUpdate, scope: OrganisationScoped, db: DbSession, request: Request
) -> Any:
    run = scope.get(db, ProfileRun, id, for_update=True)
    settings: Settings = request.app.state.settings
    if len(set(body.strategic_intent)) != len(body.strategic_intent):
        raise InvalidField("strategic_intent", "Strategic intent is not valid.")
    notes = body.notes.strip() if body.notes else None
    if notes and len(notes) > settings.buyer_notes_max_chars:
        raise InvalidField("notes", "Notes are too long.")
    value = StoredContext(
        relationship=body.relationship,
        current_share_pct=body.current_share_pct,
        contract_end_date=body.contract_end_date,
        strategic_intent=body.strategic_intent,
        notes=notes or None,
    )
    row = _write(db, scope, run, BUYER_CONTEXT, dump_context(value), body.version)
    if row is None:
        current = stored(db, run.id, BUYER_CONTEXT)
        return _conflict(
            context_out(current, _email(db, scope, current)) if current is not None else None
        )
    return context_out(row, _email(db, scope, row))


@router.put("/{id}/buyer-inputs/{field}", response_model=BuyerInputOut)
def put_buyer_input(
    id: str,
    field: str,
    body: BuyerInputUpdate,
    scope: OrganisationScoped,
    db: DbSession,
    request: Request,
) -> Any:
    run = scope.get(db, ProfileRun, id, for_update=True)
    settings: Settings = request.app.state.settings
    definition: ProfileDefinition = request.app.state.profile_definition
    buyer_fields = {item.id for item in definition.fields() if item.kind == "buyer"}
    # A field that is not of kind `buyer` (the reserved fields included) is never a free-text
    # input of the member: it is facts or assessment, or has its own structured endpoint.
    if field in RESERVED_FIELDS or field not in buyer_fields:
        raise InvalidField("field", "This field is not a buyer field.")
    if len(body.text) > settings.buyer_text_max_chars:
        raise InvalidField("text", "Text is too long.")
    row = _write(db, scope, run, field, body.text, body.version)
    if row is None:
        current = stored(db, run.id, field)
        return _conflict(
            input_out(current, _email(db, scope, current)) if current is not None else None
        )
    return input_out(row, _email(db, scope, row))


@router.get("/{id}/buyer-inputs", response_model=BuyerInputsOut)
def get_buyer_inputs(id: str, scope: OrganisationScoped, db: DbSession) -> BuyerInputsOut:
    """What the members saved for the profile: criteria, buyer context and the buyer fields, each
    with its version (to send with the next edit), who saved it and when."""
    run = scope.get(db, ProfileRun, id)  # the one 404 for another organisation
    rows = list(db.scalars(scope.select(BuyerInput).where(BuyerInput.run_id == run.id)))
    emails = user_emails(db, scope, {row.updated_by for row in rows})

    def email(row: BuyerInput) -> str | None:
        return emails.get(row.updated_by) if row.updated_by else None

    by_field = {row.field: row for row in rows}
    criteria = by_field.get(FIT_CRITERIA)
    context = by_field.get(BUYER_CONTEXT)
    return BuyerInputsOut(
        criteria=criteria_out(criteria, email(criteria)) if criteria is not None else None,
        buyer_context=context_out(context, email(context)) if context is not None else None,
        inputs=[
            input_out(row, email(row))
            for row in sorted(rows, key=lambda item: item.field)
            if row.field not in RESERVED_FIELDS
        ],
    )
