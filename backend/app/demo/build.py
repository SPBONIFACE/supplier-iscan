"""Copy the finished runs of the demo organisation into read-only `DemoProfile` records (#50).

The demo organisation is a configuration value (`DEMO_ORGANISATION_ID`). The operator fills it
with runs of synthetic or public companies, by the usual run flow, and chooses which of them make
the demo by leaving only those finished runs there. This module never starts a run, never calls a
model and never crawls: it only reads what the organisation already holds.

What is stripped, so that no person name and no personal data is copied:
- every fact of a field that `concerns_people` in the profile definition (management, owners);
- authors of sources, the reviewers' ids and emails, and the ids of runs, facts, statements and
  sources (new ids are drawn, so a real id never opens a demo route);
- statements that cite a dropped fact, fit statements and statements that cite the buyer's
  context (the buyer's own criteria and notes are not part of the demo);
- natural-person businesses (not assessed, personal data) are not copied at all.
Quotes are copied as stored: they were redacted before storage (F2), and carry `quote_redacted`.
"""

import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal
from app.config import Settings
from app.demo import pdf_cache
from app.models import DemoProfile, ProfileRun, Source, SupplierIdentity
from app.organisations.scope import OrganisationScope
from app.profile_definition import ProfileDefinition
from app.runs.routes import AssessmentOut, FactOut, RunOut, _one, get_assessment, list_facts

COPIED_STATUSES = ("completed", "partial")


class DemoOrganisationRefused(Exception):
    """The organisation is not the configured demo organisation (the message says why)."""


@dataclass(frozen=True)
class Copied:
    profiles: int
    skipped_natural_person: int


def check_organisation(settings: Settings, organisation_id: uuid.UUID) -> None:
    """Only the configured demo organisation may be copied: no customer profile becomes a demo
    profile, whatever the caller passes."""
    if settings.demo_organisation_id is None:
        raise DemoOrganisationRefused("DEMO_ORGANISATION_ID is not set: nothing can be copied.")
    if organisation_id != settings.demo_organisation_id:
        raise DemoOrganisationRefused(
            "That organisation is not the configured demo organisation: nothing was copied."
        )


def strip_facts(
    facts: list[FactOut], definition: ProfileDefinition
) -> tuple[list[dict[str, Any]], dict[uuid.UUID, uuid.UUID]]:
    """The facts as the demo stores them, and the map from old to new fact ids."""
    people = {
        field.id
        for section in definition.sections
        for field in section.fields
        if field.concerns_people
    }
    kept: list[dict[str, Any]] = []
    ids: dict[uuid.UUID, uuid.UUID] = {}
    for fact in facts:
        if fact.field in people:
            continue
        data = fact.model_dump(mode="json")
        ids[fact.id] = uuid.uuid4()
        data.update(
            id=str(ids[fact.id]),
            author=None,
            source_id=None,
            reviewed_by=None,
            reviewed_by_email=None,
        )
        kept.append(data)
    return kept, ids


def strip_assessment(
    assessment: AssessmentOut, fact_ids: dict[uuid.UUID, uuid.UUID]
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for item in assessment.items:
        if item.kind == "fit" or item.cites_buyer_context:
            continue
        if any(cited not in fact_ids for cited in item.cited_fact_ids):
            continue  # it rests on a fact that is not copied
        data = item.model_dump(mode="json")
        data.update(
            id=str(uuid.uuid4()),
            cited_fact_ids=[str(fact_ids[cited]) for cited in item.cited_fact_ids],
            buyer_context_version=None,
            buyer_context_outdated=False,
        )
        data["provenance"].update(reviewed_by=None, reviewed_by_email=None)
        items.append(data)
    data = assessment.model_dump(mode="json")
    data.update(
        items=items,
        buyer_context_version=None,
        current_buyer_context_version=None,
        fit_message=None,
        pending=[],
        rejected_statements=0,
    )
    return data


def demo_run_header(run: RunOut, facts: list[dict[str, Any]]) -> dict[str, Any]:
    """The `DemoRun` of a profile, without its id (the record's own id is added when read)."""
    return {
        "supplier_name": run.supplier_name or "",
        "supplier_website": run.supplier_website,
        "supplier_country": run.supplier_country,
        "supplier_sector": run.supplier_sector,
        "natural_person": False,
        "status": run.status,
        "identity_to_verify": run.identity_to_verify,
        "uncovered_sections": run.uncovered_sections,
        "partial_explanation": run.partial_explanation,
        "excluded_sources": [source.model_dump(mode="json") for source in run.excluded_sources],
        "proposed_facts": sum(1 for fact in facts if fact["status"] == "proposed"),
        "finished_at": (run.finished_at or run.created_at).isoformat(),
        "profile_definition_hash": run.profile_definition_hash,
    }


def build_demo_profile(
    db: Session, scope: OrganisationScope, request: Any, run: ProfileRun, position: int
) -> DemoProfile:
    definition: ProfileDefinition = request.app.state.profile_definition
    session = cast(Any, db)
    header = _one(session, scope, run, False)
    facts, fact_ids = strip_facts(
        list_facts(str(run.id), scope, session, request).items, definition
    )
    assessment = strip_assessment(get_assessment(str(run.id), scope, session, request), fact_ids)
    sources = [
        {"url": s.url, "fetched_at": s.fetched_at.isoformat(), "content_type": s.content_type}
        for s in db.scalars(
            select(Source).where(Source.run_id == run.id).order_by(Source.fetched_at, Source.url)
        )
    ]
    return DemoProfile(
        position=position,
        supplier_name=header.supplier_name or "",
        run=demo_run_header(header, facts),
        facts=facts,
        assessment=assessment,
        sources=sources,
    )


def load_demo_profiles(
    db: Session, settings: Settings, definition: ProfileDefinition, organisation_id: uuid.UUID
) -> Copied:
    """Replace the demo set with the finished runs of the demo organisation. One transaction: the
    old set stays when anything fails. Raises DemoOrganisationRefused for any other organisation."""
    check_organisation(settings, organisation_id)
    # The operator acts for the demo organisation; the read functions of the member API are reused
    # as they are, with a request stand-in that carries only the state they read.
    scope = OrganisationScope(
        Principal(
            user_id=uuid.uuid4(),
            email="",
            role="member",
            organisation_id=organisation_id,
            session_id=uuid.uuid4(),
        )
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings, profile_definition=definition))
    )
    runs = db.scalars(
        select(ProfileRun)
        .where(
            ProfileRun.organisation_id == organisation_id, ProfileRun.status.in_(COPIED_STATUSES)
        )
        .order_by(ProfileRun.created_at, ProfileRun.id)
    ).all()
    profiles: list[DemoProfile] = []
    skipped = 0
    for run in runs:
        identity = db.scalar(select(SupplierIdentity).where(SupplierIdentity.id == run.identity_id))
        if identity is None or identity.natural_person:
            skipped += 1
            continue
        profiles.append(build_demo_profile(db, scope, request, run, len(profiles)))
    db.execute(delete(DemoProfile))
    db.add_all(profiles)
    db.commit()
    pdf_cache.clear()  # the new profiles have new ids; this process drops the old files too
    return Copied(profiles=len(profiles), skipped_natural_person=skipped)
