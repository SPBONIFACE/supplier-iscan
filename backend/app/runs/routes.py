"""/runs (openapi.yaml, tag `runs`). Endpoints only queue, flag or read; no stage executes here.

An administrator is scoped like any member (their own organisation) but gets run metadata only:
`supplier_name` is null for them (spec, Data model & ownership).
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app import queue
from app.assessment.routes import ENTER_CRITERIA, pending_parts
from app.assessment.rules import NOT_ASSESSED, RECOMMENDATION_KINDS
from app.buyer.values import run_criteria, stored
from app.config import Settings
from app.crawl.store import excluded_sources
from app.db import DbSession, utc_now
from app.errors import not_found
from app.extraction.settings import load_extraction_settings
from app.limits.partial import RECOMMENDATIONS
from app.models import (
    AssessmentItem,
    Fact,
    ProfileRun,
    RunFailure,
    Source,
    SupplierIdentity,
    UsageEvent,
)
from app.models.buyer import BUYER_CONTEXT
from app.models.runs import FINISHED_STATUSES
from app.organisations.scope import OrganisationScope, OrganisationScoped
from app.profile_definition import ProfileDefinition
from app.providers.usage import run_usage_totals
from app.runs.executor import RUN_JOB

router = APIRouter(prefix="/runs", tags=["runs"])

LIST_LIMIT = 100
ALREADY_FINISHED = "The run has already finished."
NOT_PAUSED = "The run is not paused."
INSUFFICIENT_SOURCES = (
    "No public source could be collected for this supplier, so no profile could be built. "
    "The failure log shows what was tried. This run does not count against your quota."
)


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


class ExcludedSourceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    message: str


class RunOut(BaseModel):
    """Mirrors components/schemas/Run."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    identity_id: uuid.UUID
    supplier_name: str | None
    supplier_website: str | None
    supplier_country: str | None
    supplier_sector: str | None
    natural_person: bool
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
    excluded_sources: list[ExcludedSourceOut]
    identity_to_verify: bool
    grounding_failures: int
    invalid_items: int
    uncovered_sections: list[str]
    partial_explanation: str | None
    proposed_facts: int
    insufficient_sources_explanation: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SourceOut(BaseModel):
    """Mirrors components/schemas/Source (the text is not listed)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    url: str
    fetched_at: datetime
    content_type: str


class SourceListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SourceOut]


class RunFailureOut(BaseModel):
    """Mirrors components/schemas/RunFailure."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    url: str | None
    strategy: Literal["website", "sitemap", "retrieval"]
    kind: str
    next_strategy: Literal["website", "sitemap", "retrieval"] | None
    message: str
    created_at: datetime


class RunFailureListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RunFailureOut]


class FactOut(BaseModel):
    """Mirrors components/schemas/Fact."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    section: str
    field: str
    status: Literal["proposed", "approved", "corrected", "not_found"]
    value: str | None
    quote: str | None
    quote_redacted: bool
    source_id: uuid.UUID | None
    source_url: str | None
    source_type: Literal["supplier_claim", "third_party"] | None
    publisher: str | None
    author: str | None
    fetched_at: datetime | None
    verification_url: str | None
    original_value: str | None
    version: int
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None


class AssessmentProvenanceOut(BaseModel):
    """Mirrors components/schemas/AssessmentProvenance."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model_id: str
    model_version: str
    prompt_id: str
    prompt_version: str
    generated_at: datetime
    status: Literal["ai_draft", "approved", "corrected", "deleted"]
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None


class AssessmentStatementOut(BaseModel):
    """Mirrors components/schemas/AssessmentStatement."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    kind: Literal[
        "strength",
        "weakness",
        "opportunity",
        "threat",
        "risk_indicator",
        "evidence_gap",
        "fit",
        "procurement_implication",
        "relationship_level",
        "contract_approach",
        "volume_share",
        "next_action",
        "procurement_priority",
    ]
    text: str
    level: Literal["low", "medium", "high"] | None
    label: Literal["strategic", "preferred", "transactional"] | None
    timing: str | None
    cited_fact_ids: list[uuid.UUID]
    cites_buyer_context: bool
    gap_evidence: str | None
    buyer_context_version: int | None
    buyer_context_outdated: bool
    provenance: AssessmentProvenanceOut
    version: int
    original_text: str | None


class FinancialDocumentOut(BaseModel):
    """Mirrors components/schemas/FinancialDocument."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["income_statement", "balance_sheet", "notes", "audit_report"]
    scope: Literal["supplier_entity", "group"]
    access: Literal[
        "public_download",
        "free_registration",
        "paid",
        "reduced_disclosure",
        "confidentiality_declared",
        "no_filing_identified",
        "registry_unavailable",
    ]
    registry_link: str | None


class FinancialGuidanceOut(BaseModel):
    """Mirrors components/schemas/FinancialGuidance."""

    model_config = ConfigDict(extra="forbid")

    country: str | None
    financial_year: int
    configured: bool
    example_table: bool
    registry_name: str | None
    registry_url: str | None
    last_checked: str | None
    documents: list[FinancialDocumentOut]
    missing_evidence: list[str]
    documents_to_request: list[str]
    message: str


class AssessmentOut(BaseModel):
    """Mirrors components/schemas/Assessment."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "drafted", "partial", "not_assessed"]
    message: str | None
    buyer_context_version: int | None
    current_buyer_context_version: int | None
    fit_message: str | None
    pending: list[Literal["fit", "recommendations"]]
    financial_guidance: FinancialGuidanceOut | None
    rejected_statements: int
    items: list[AssessmentStatementOut]


class FactListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FactOut]


class RunListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RunOut]


def hide_names(request: Request, scope: OrganisationScope) -> bool:
    """Supplier names are content of the organisation: only its members read them. On a hosted
    instance the administrator gets run metadata only. On a self-hosted instance the local
    administrator is a member of the default organisation and reads its content (owner decision,
    like `OrganisationScoped`).
    """
    settings: Settings = request.app.state.settings
    return scope.principal.role == "admin" and not settings.organisations_skip_activation


def _run_out(
    db: DbSession,
    scope: OrganisationScope,
    run: ProfileRun,
    identity: SupplierIdentity | None,
    hide_names: bool,
    excluded: list[dict[str, str]],
    proposed_facts: int,
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
            # Run metadata only for an administrator: nothing that identifies the supplier.
            "supplier_name": None if hide_names or identity is None else identity.legal_name,
            "supplier_website": None if hide_names or identity is None else identity.website,
            "supplier_country": None if hide_names or identity is None else identity.country,
            "supplier_sector": None if hide_names or identity is None else identity.sector,
            "natural_person": bool(identity and identity.natural_person and not hide_names),
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
            "excluded_sources": excluded,
            "identity_to_verify": run.identity_to_verify,
            "grounding_failures": run.grounding_failures,
            "invalid_items": run.invalid_items,
            "uncovered_sections": run.uncovered_sections or [],
            "partial_explanation": run.partial_explanation,
            "proposed_facts": proposed_facts,
            "insufficient_sources_explanation": (
                INSUFFICIENT_SOURCES if run.status == "insufficient_sources" else None
            ),
            "created_at": run.created_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }
    )


def proposed_counts(
    db: DbSession, organisation_id: uuid.UUID, run_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Per run, the number of facts still `proposed` (runs without one are absent)."""
    rows = db.execute(
        select(Fact.run_id, func.count())
        .where(
            Fact.organisation_id == organisation_id,
            Fact.run_id.in_(run_ids),
            Fact.status == "proposed",
        )
        .group_by(Fact.run_id)
    )
    return {run_id: count for run_id, count in rows}


def fact_out(fact: Fact, certification: bool, certsearch: str) -> FactOut:
    """A fact as the API shows it; `certification` is the field's flag in the profile definition."""
    return FactOut(
        id=fact.id,
        section=fact.section,
        field=fact.field,
        status=fact.status,  # type: ignore[arg-type]  # constrained by the table
        value=fact.value,
        quote=fact.quote,
        quote_redacted=fact.quote_redacted,
        source_id=fact.source_id,
        source_url=fact.source_url,
        source_type=fact.source_type,  # type: ignore[arg-type]
        publisher=fact.publisher,
        author=fact.author,
        fetched_at=fact.fetched_at,
        verification_url=certsearch if certification and fact.status != "not_found" else None,
        original_value=fact.original_value,
        version=fact.version,
        reviewed_by=fact.reviewed_by,
        reviewed_at=fact.reviewed_at,
    )


def statement_out(row: AssessmentItem, current_context: int | None) -> AssessmentStatementOut:
    """A statement as the API shows it; `current_context` is the stored buyer-context version."""
    return AssessmentStatementOut(
        id=row.id,
        kind=row.kind,  # type: ignore[arg-type]  # constrained by the table
        text=row.text,
        level=row.level,  # type: ignore[arg-type]
        label=row.label,  # type: ignore[arg-type]
        timing=row.timing,
        cited_fact_ids=[uuid.UUID(value) for value in row.cited_fact_ids],
        cites_buyer_context=row.cites_buyer_context,
        gap_evidence=row.gap_evidence,
        buyer_context_version=row.buyer_context_version,
        # A recommendation drafted before the current context (or without any) is flagged.
        buyer_context_outdated=(
            current_context is not None
            and row.kind in RECOMMENDATION_KINDS
            and (row.buyer_context_version is None or row.buyer_context_version < current_context)
        ),
        provenance=AssessmentProvenanceOut(
            provider=row.provider,
            model_id=row.model_id,
            model_version=row.model_version,
            prompt_id=row.prompt_id,
            prompt_version=row.prompt_version,
            generated_at=row.generated_at,
            status=row.status,  # type: ignore[arg-type]
            reviewed_by=row.reviewed_by,
            reviewed_at=row.reviewed_at,
        ),
        version=row.version,
        original_text=row.original_text,
    )


def _one(db: DbSession, scope: OrganisationScope, run: ProfileRun, hide: bool) -> RunOut:
    identity = db.scalar(
        scope.select(SupplierIdentity).where(SupplierIdentity.id == run.identity_id)
    )
    excluded = excluded_sources(db, scope.organisation_id, [run.id]).get(run.id, [])
    proposed = proposed_counts(db, scope.organisation_id, [run.id]).get(run.id, 0)
    return _run_out(db, scope, run, identity, hide, excluded, proposed)


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=RunOut)
def start_run(body: RunStart, scope: OrganisationScoped, db: DbSession, request: Request) -> RunOut:
    identity = scope.get(db, SupplierIdentity, body.identity_id)
    if identity.confirmed_at is None:
        # Same answer as an unknown identity: only a confirmed identity starts a run.
        raise not_found()
    run = scope.new(
        ProfileRun,
        identity_id=identity.id,
        created_by=scope.principal.user_id,
        # The definition this run uses, so that its facts stay interpretable after a change.
        profile_definition_hash=request.app.state.profile_definition.content_hash,
        prompt_set_hash=request.app.state.prompt_set.content_hash,
    )
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
    return _run_out(db, scope, run, identity, hide_names(request, scope), [], 0)


@router.get("", response_model=RunListOut)
def list_runs(scope: OrganisationScoped, db: DbSession, request: Request) -> RunListOut:
    runs = db.scalars(
        scope.select(ProfileRun).order_by(ProfileRun.created_at.desc()).limit(LIST_LIMIT)
    ).all()
    hidden = hide_names(request, scope)
    identities = {
        identity.id: identity
        for identity in db.scalars(
            select(SupplierIdentity).where(
                SupplierIdentity.organisation_id == scope.organisation_id,
                SupplierIdentity.id.in_({run.identity_id for run in runs}),
            )
        )
    }
    ids = [run.id for run in runs]
    excluded = excluded_sources(db, scope.organisation_id, ids)
    proposed = proposed_counts(db, scope.organisation_id, ids)
    return RunListOut(
        items=[
            _run_out(
                db,
                scope,
                run,
                identities.get(run.identity_id),
                hidden,
                excluded.get(run.id, []),
                proposed.get(run.id, 0),
            )
            for run in runs
        ]
    )


@router.get("/{id}", response_model=RunOut)
def get_run(id: str, scope: OrganisationScoped, db: DbSession, request: Request) -> RunOut:
    return _one(db, scope, scope.get(db, ProfileRun, id), hide_names(request, scope))


@router.get("/{id}/sources", response_model=SourceListOut)
def list_sources(id: str, scope: OrganisationScoped, db: DbSession) -> SourceListOut:
    run = scope.get(db, ProfileRun, id)  # the one 404 for an unknown or another organisation's run
    rows = db.scalars(
        scope.select(Source).where(Source.run_id == run.id).order_by(Source.fetched_at, Source.url)
    ).all()
    return SourceListOut(items=[SourceOut.model_validate(row) for row in rows])


@router.get("/{id}/failures", response_model=RunFailureListOut)
def list_failures(id: str, scope: OrganisationScoped, db: DbSession) -> RunFailureListOut:
    run = scope.get(db, ProfileRun, id)  # the one 404 for an unknown or another organisation's run
    rows = db.scalars(
        scope.select(RunFailure)
        .where(RunFailure.run_id == run.id)
        .order_by(RunFailure.position, RunFailure.id)
    ).all()
    return RunFailureListOut(items=[RunFailureOut.model_validate(row) for row in rows])


@router.get("/{id}/facts", response_model=FactListOut)
def list_facts(id: str, scope: OrganisationScoped, db: DbSession, request: Request) -> FactListOut:
    """One entry per `fact` field of the profile definition that extraction has stored, in the
    order of the definition. A field with no kept value is `not_found`, with no value and no
    quote: never a negative statement about the supplier."""
    run = scope.get(db, ProfileRun, id)  # the one 404 for an unknown or another organisation's run
    stored = {
        fact.field: fact for fact in db.scalars(scope.select(Fact).where(Fact.run_id == run.id))
    }
    certsearch = load_extraction_settings().certsearch_url
    definition: ProfileDefinition = request.app.state.profile_definition
    items = []
    for section in definition.sections:
        for item in section.fields:
            fact = stored.get(item.id)
            if item.kind != "fact" or fact is None:
                continue
            items.append(fact_out(fact, item.certification, certsearch))
    return FactListOut(items=items)


@router.get("/{id}/assessment", response_model=AssessmentOut)
def get_assessment(
    id: str, scope: OrganisationScoped, db: DbSession, request: Request
) -> AssessmentOut:
    """The AI-drafted statements of the run, with their cited facts and provenance. A
    natural-person business is not assessed: no statement exists and the message says so."""
    run = scope.get(db, ProfileRun, id)  # the one 404 for an unknown or another organisation's run
    identity = db.scalar(
        scope.select(SupplierIdentity).where(SupplierIdentity.id == run.identity_id)
    )
    if identity is not None and identity.natural_person:
        return AssessmentOut(
            status="not_assessed",
            message=NOT_ASSESSED,
            buyer_context_version=None,
            current_buyer_context_version=None,
            fit_message=NOT_ASSESSED,
            pending=[],
            financial_guidance=None,
            rejected_statements=0,
            items=[],
        )
    rows = db.scalars(
        scope.select(AssessmentItem)
        .where(AssessmentItem.run_id == run.id, AssessmentItem.status != "deleted")
        .order_by(AssessmentItem.position)
    ).all()
    context_row = stored(db, run.id, BUYER_CONTEXT)
    current = context_row.version if context_row is not None else None
    items = [statement_out(row, current) for row in rows]
    versions = [item.buyer_context_version for item in items if item.buyer_context_version]
    guidance: dict[str, Any] | None = next(
        (row.guidance for row in rows if row.provider == "rules" and row.guidance), None
    )
    definition: ProfileDefinition = request.app.state.profile_definition
    assessment_ids = {
        section.id
        for section in definition.sections
        if any(item.kind == "assessment" for item in section.fields)
    } | {RECOMMENDATIONS}
    # A run that stopped at its cost budget before the assessment was complete must not look
    # complete, nor "pending" for ever (#30).
    cut_short = run.status == "partial" and bool(assessment_ids & set(run.uncovered_sections or []))
    return AssessmentOut(
        status=(
            "partial"
            if cut_short
            else "drafted"
            if run.assessment_drafted_at is not None
            else "pending"
        ),
        message=None,
        buyer_context_version=max(versions) if versions else None,
        current_buyer_context_version=current,
        fit_message=None if run_criteria(db, run.id) else ENTER_CRITERIA,
        pending=pending_parts(db, run.id),  # type: ignore[arg-type]
        financial_guidance=(
            FinancialGuidanceOut.model_validate(guidance) if guidance is not None else None
        ),
        rejected_statements=run.rejected_statements,
        items=items,
    )


@router.post("/{id}/stop", response_model=RunOut)
def stop_run(id: str, scope: OrganisationScoped, db: DbSession, request: Request) -> RunOut:
    run = scope.get(db, ProfileRun, id, for_update=True)
    if run.status in FINISHED_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=ALREADY_FINISHED)
    run.stop_requested = True
    if run.status in ("queued", "paused"):
        # Nothing is executing: it ends now. A queued run's job finds it stopped and does nothing.
        run.status = "stopped"
        run.finished_at = utc_now()
    db.commit()
    return _one(db, scope, run, hide_names(request, scope))


@router.post("/{id}/resume", status_code=status.HTTP_202_ACCEPTED, response_model=RunOut)
def resume_run(id: str, scope: OrganisationScoped, db: DbSession, request: Request) -> RunOut:
    run = scope.get(db, ProfileRun, id, for_update=True)
    if run.status != "paused":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NOT_PAUSED)
    run.status = "queued"
    run.pause_dependency = None
    run.pause_reason = None
    run.counts_against_quota = True
    queue.enqueue(db, RUN_JOB, {"run_id": str(run.id)})
    db.commit()
    return _one(db, scope, run, hide_names(request, scope))
