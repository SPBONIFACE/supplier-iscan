"""PATCH /facts/{id} and PATCH /assessment-statements/{id} (openapi.yaml, tag `review`).

Any member of the owning organisation approves or corrects a fact, and approves, corrects or
deletes an assessment statement. Rules that hold for both:

- The AI value is never lost: a first correction copies it to `original_value` / `original_text`,
  a later correction replaces only the member's value. The quote, the source and the provenance of
  the draft are never touched. A deleted statement keeps its row.
- Each change names the version the member read. The row is locked for the write, so two members
  reviewing at once are told apart: the later one gets 409 with the stored value and nothing is
  written.
- Only a finished run is reviewed: while it is queued, running or paused the answer is 409.
- Nothing here calls a model. The submitted text is never echoed back or logged; it is the
  member's content, possibly with personal data, and is redacted like any other text before it
  reaches a provider (`RedactionGate`, used by the assessment stage for the facts it sends).
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.buyer.values import stored
from app.config import Settings
from app.db import DbSession, utc_now
from app.errors import InvalidField
from app.extraction.settings import load_extraction_settings
from app.models import AssessmentItem, Fact, ProfileRun
from app.models.buyer import BUYER_CONTEXT
from app.models.runs import FINISHED_STATUSES
from app.organisations.scope import OrganisationScope, OrganisationScoped
from app.profile_definition import ProfileDefinition
from app.runs.routes import AssessmentStatementOut, FactOut, fact_out, statement_out

router = APIRouter(tags=["review"])

IN_PROGRESS = "The run is still in progress."
OUTDATED = (
    "Someone reviewed this since you read it. Check the current version before reviewing again."
)
NOTHING_TO_REVIEW = "No public evidence found for this field: there is no value to review."
ALREADY_CORRECTED = "This value was corrected. Correct it again to change it."
STATEMENT_CORRECTED = "This statement was corrected. Correct it again to change it."
DELETED = "This statement was deleted."


class FactReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "corrected"]
    value: str | None = None
    version: int = Field(ge=1)


class StatementReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "corrected", "deleted"]
    text: str | None = None
    version: int = Field(ge=1)


def _conflict(detail: str, current: BaseModel | None = None) -> JSONResponse:
    content: dict[str, object] = {"detail": detail}
    if current is not None:
        content["current"] = current.model_dump(mode="json")
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=content)


def _finished(db: DbSession, run_id: uuid.UUID) -> bool:
    run = db.get(ProfileRun, run_id)
    return run is not None and run.status in FINISHED_STATUSES


def _corrected_text(raw: str | None, field: str, limit: int) -> str:
    """The member's corrected text, stripped; 422 (never echoing it) when blank or too long."""
    text = (raw or "").strip()
    if not text:
        raise InvalidField(field, f"A corrected {field} is required.")
    if len(text) > limit:
        raise InvalidField(field, f"The {field} is too long.")
    return text


def _no_text(raw: str | None, field: str) -> None:
    if raw is not None:
        raise InvalidField(field, f"A {field} is only accepted with a correction.")


def _certification(definition: ProfileDefinition, field: str) -> bool:
    return any(item.certification for item in definition.fields() if item.id == field)


@router.patch("/facts/{id}", response_model=FactOut)
def review_fact(
    id: str,
    body: FactReview,
    scope: OrganisationScoped,
    db: DbSession,
    request: Request,
) -> FactOut | JSONResponse:
    fact = scope.get(db, Fact, id, for_update=True)  # the one 404 for another organisation
    settings: Settings = request.app.state.settings
    definition: ProfileDefinition = request.app.state.profile_definition
    corrected = (
        _corrected_text(body.value, "value", settings.review_text_max_chars)
        if body.status == "corrected"
        else None
    )
    if body.status == "approved":
        _no_text(body.value, "value")

    def out() -> FactOut:
        return fact_out(
            fact,
            _certification(definition, fact.field),
            load_extraction_settings().certsearch_url,
        )

    if not _finished(db, fact.run_id):
        return _conflict(IN_PROGRESS)
    if fact.version != body.version:
        return _conflict(OUTDATED, out())
    if fact.status == "not_found":
        return _conflict(NOTHING_TO_REVIEW)
    if body.status == "approved":
        if fact.status == "corrected":
            return _conflict(ALREADY_CORRECTED)
        if fact.status == "approved":
            return out()  # already approved at this version: nothing to record
    else:
        if fact.original_value is None:
            fact.original_value = fact.value  # the AI value, kept by the first correction only
        fact.value = corrected
    fact.status = body.status
    fact.version += 1
    fact.reviewed_by = scope.principal.user_id
    fact.reviewed_at = utc_now()
    db.commit()
    db.refresh(fact)
    return out()


def _statement(scope: OrganisationScope, db: DbSession, id: str) -> AssessmentItem:
    return scope.get(db, AssessmentItem, id, for_update=True)


@router.patch("/assessment-statements/{id}", response_model=AssessmentStatementOut)
def review_statement(
    id: str,
    body: StatementReview,
    scope: OrganisationScoped,
    db: DbSession,
    request: Request,
) -> AssessmentStatementOut | JSONResponse:
    row = _statement(scope, db, id)  # the one 404 for another organisation
    settings: Settings = request.app.state.settings
    corrected = (
        _corrected_text(body.text, "text", settings.review_text_max_chars)
        if body.status == "corrected"
        else None
    )
    if body.status != "corrected":
        _no_text(body.text, "text")

    def out() -> AssessmentStatementOut:
        context = stored(db, row.run_id, BUYER_CONTEXT)
        return statement_out(row, context.version if context is not None else None)

    if not _finished(db, row.run_id):
        return _conflict(IN_PROGRESS)
    if row.status == "deleted":
        return _conflict(DELETED, out())
    if row.version != body.version:
        return _conflict(OUTDATED, out())
    if body.status == "approved":
        if row.status == "corrected":
            return _conflict(STATEMENT_CORRECTED)
        if row.status == "approved":
            return out()
    elif body.status == "corrected":
        assert corrected is not None  # noqa: S101 - checked above
        if row.original_text is None:
            row.original_text = row.text  # the AI text, kept by the first correction only
        row.text = corrected
    row.status = body.status
    row.version += 1
    row.reviewed_by = scope.principal.user_id
    row.reviewed_at = utc_now()
    db.commit()
    db.refresh(row)
    return out()
