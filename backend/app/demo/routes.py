"""/demo (openapi.yaml, tag `demo`): the public, read-only demo (#50).

No sign-in. These routes read the `DemoProfile` table and nothing else: no run, organisation,
user, usage or provider table, and no provider, queue or crawler. The database session is a
read-only transaction, so that even a mistake in this module cannot write. The id of a real run,
an unknown id and a malformed id all answer the one 404.
"""

import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth.access import PUBLIC
from app.comparison.routes import _distinct
from app.config import Settings
from app.db import Database, utc_now
from app.errors import InvalidField, not_found, parse_resource_id
from app.models import DemoProfile
from app.pdf.disclaimer import DisclaimerError, disclaimer_text
from app.pdf.render import CardInput, PdfUnavailable, render_pdf
from app.pdf.routes import UNAVAILABLE, safe_filename
from app.profile_definition import ProfileDefinition
from app.profile_routes import ProfileDefinitionOut, render
from app.runs.routes import AssessmentOut, ExcludedSourceOut, FactOut, RunOut

router = APIRouter(prefix="/demo", tags=["demo"], dependencies=[PUBLIC])

Lang = Literal["en", "fr"]
LangQuery = Annotated[Lang, Query()]
DEMO_ORGANISATION_NAME = "Supplier iScan demo"


def demo_session(request: Request) -> Iterator[Session]:
    """One read-only transaction per request: a write raises instead of happening."""
    database: Database = request.app.state.database
    with database.session() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        yield session


DemoDb = Annotated[Session, Depends(demo_session)]


class DemoRunOut(BaseModel):
    """Mirrors components/schemas/DemoRun."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    supplier_name: str
    supplier_website: str | None
    supplier_country: str | None
    supplier_sector: str | None
    natural_person: bool
    status: Literal["completed", "partial"]
    identity_to_verify: bool
    uncovered_sections: list[str]
    partial_explanation: str | None
    excluded_sources: list[ExcludedSourceOut]
    proposed_facts: int
    finished_at: str
    profile_definition_hash: str | None


class DemoSourceOut(BaseModel):
    """Mirrors components/schemas/DemoSource."""

    model_config = ConfigDict(extra="forbid")

    url: str
    fetched_at: str
    content_type: str


class DemoProfileListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DemoRunOut]
    disclaimer: str


class DemoProfileOut(BaseModel):
    """Mirrors components/schemas/DemoProfile."""

    model_config = ConfigDict(extra="forbid")

    run: DemoRunOut
    facts: list[FactOut]
    assessment: AssessmentOut
    sources: list[DemoSourceOut]
    disclaimer: str


class DemoComparisonProfileOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: DemoRunOut
    facts: list[FactOut]


class DemoComparisonOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DemoComparisonProfileOut]
    disclaimer: str


def _disclaimer(request: Request, lang: Lang) -> str:
    try:
        return disclaimer_text(request.app.state.settings, lang)
    except DisclaimerError:
        # Generic: the demo does not show without its disclaimer, and says nothing about why.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=UNAVAILABLE) from None


def _run(row: DemoProfile) -> DemoRunOut:
    return DemoRunOut.model_validate({**row.run, "id": row.id})


def _one(db: Session, raw_id: str) -> DemoProfile:
    row = db.scalar(select(DemoProfile).where(DemoProfile.id == parse_resource_id(raw_id)))
    if row is None:
        raise not_found()
    return row


@router.get("/profile-definition", response_model=ProfileDefinitionOut)
def get_demo_profile_definition(
    request: Request, language: Annotated[Lang, Query()] = "en"
) -> ProfileDefinitionOut:
    definition: ProfileDefinition = request.app.state.profile_definition
    return render(definition, language)


@router.get("/profiles", response_model=DemoProfileListOut)
def list_demo_profiles(request: Request, db: DemoDb, lang: LangQuery = "en") -> DemoProfileListOut:
    rows = db.scalars(select(DemoProfile).order_by(DemoProfile.position, DemoProfile.id)).all()
    return DemoProfileListOut(
        items=[_run(row) for row in rows], disclaimer=_disclaimer(request, lang)
    )


@router.get("/profiles/{id}", response_model=DemoProfileOut)
def get_demo_profile(
    id: str, request: Request, db: DemoDb, lang: LangQuery = "en"
) -> DemoProfileOut:
    row = _one(db, id)
    return DemoProfileOut(
        run=_run(row),
        facts=[FactOut.model_validate(fact) for fact in row.facts],
        assessment=AssessmentOut.model_validate(row.assessment),
        sources=[DemoSourceOut.model_validate(source) for source in row.sources],
        disclaimer=_disclaimer(request, lang),
    )


@router.get("/comparison", response_model=DemoComparisonOut)
def get_demo_comparison(
    request: Request,
    db: DemoDb,
    profile_ids: Annotated[list[str], Query()],
    lang: LangQuery = "en",
) -> DemoComparisonOut:
    maximum: int = request.app.state.settings.comparison_max_profiles
    wanted = _distinct(profile_ids)
    if not 2 <= len(wanted) <= maximum:
        raise InvalidField("profile_ids", f"Choose between 2 and {maximum} different profiles.")
    ids = list(dict.fromkeys(parse_resource_id(value) for value in wanted))
    found = {row.id: row for row in db.scalars(select(DemoProfile).where(DemoProfile.id.in_(ids)))}
    if len(found) != len(ids):
        raise not_found()  # one unknown id, or a real run's: no partial data
    return DemoComparisonOut(
        items=[
            DemoComparisonProfileOut(
                run=_run(found[i]), facts=[FactOut.model_validate(f) for f in found[i].facts]
            )
            for i in ids
        ],
        disclaimer=_disclaimer(request, lang),
    )


def _card_run(row: DemoProfile) -> RunOut:
    """The `Run` the PDF generator reads, from the stored header: no usage, no cost, no user."""
    header = _run(row)
    return RunOut.model_validate(
        {
            "id": row.id,
            "identity_id": row.id,
            "supplier_name": header.supplier_name,
            "supplier_website": header.supplier_website,
            "supplier_country": header.supplier_country,
            "supplier_sector": header.supplier_sector,
            "natural_person": False,
            "status": header.status,
            "stage": "assessment",
            "stop_requested": False,
            "counts_against_quota": False,
            "pause_dependency": None,
            "pause_reason": None,
            "error": None,
            "profile_definition_hash": header.profile_definition_hash,
            "prompt_set_hash": None,
            "usage": {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "tool_calls": 0,
                "cost": "0",
                "roles": [],
            },
            "excluded_sources": [source.model_dump() for source in header.excluded_sources],
            "identity_to_verify": header.identity_to_verify,
            "grounding_failures": 0,
            "invalid_items": 0,
            "uncovered_sections": header.uncovered_sections,
            "partial_explanation": header.partial_explanation,
            "proposed_facts": header.proposed_facts,
            "insufficient_sources_explanation": None,
            "created_at": header.finished_at,
            "started_at": None,
            "finished_at": header.finished_at,
        }
    )


class _NoBuyerInputs(BaseModel):
    """What the card PDF reads of the buyer's own inputs: the demo has none."""

    criteria: Any = None
    buyer_context: Any = None
    inputs: list[Any] = []


def card_input(
    row: DemoProfile, settings: Settings, definition: ProfileDefinition, lang: Lang, now: datetime
) -> CardInput:
    """What the card PDF generator reads, from the stored demo profile and the demo disclaimer."""
    return CardInput(
        run=_card_run(row),
        facts=[FactOut.model_validate(fact) for fact in row.facts],
        definition=definition,
        assessment=AssessmentOut.model_validate(row.assessment),
        buyer_inputs=_NoBuyerInputs(),
        organisation_name=DEMO_ORGANISATION_NAME,
        generated_at=now,
        lang=lang,
        disclaimer=disclaimer_text(settings, lang),
    )


@router.get(
    "/profiles/{id}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_demo_profile_pdf(id: str, request: Request, db: DemoDb, lang: LangQuery = "en") -> Response:
    row = _one(db, id)
    now = utc_now()
    try:
        card = card_input(
            row, request.app.state.settings, request.app.state.profile_definition, lang, now
        )
        content = render_pdf(card)
    except (PdfUnavailable, DisclaimerError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=UNAVAILABLE) from None
    filename = safe_filename(row.supplier_name, now.strftime("%Y%m%d"))
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
