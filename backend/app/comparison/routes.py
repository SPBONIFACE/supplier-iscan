"""GET /comparison (openapi.yaml, tag `runs`): the facts of several of the organisation's runs,
field by field (spec F5).

Facts only, as the runs list them: no assessment, no score and no ranking (owner decision D-073,
5 Nov 2026), so a natural-person supplier's "Not assessed" cannot appear here as a gap or a lower
value. One id that is unknown or another organisation's makes the whole request answer the one 404,
with no partial data.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.crawl.store import excluded_sources
from app.db import DbSession
from app.errors import InvalidField, not_found, parse_resource_id
from app.extraction.settings import load_extraction_settings
from app.models import Fact, ProfileRun, SupplierIdentity
from app.models.runs import FINISHED_STATUSES
from app.organisations.scope import OrganisationScoped
from app.profile_definition import ProfileDefinition
from app.runs.routes import (
    FactOut,
    RunOut,
    _run_out,
    fact_out,
    hide_names,
    proposed_counts,
    user_emails,
)

router = APIRouter(prefix="/comparison", tags=["runs"])


class ComparisonRunOut(BaseModel):
    """Mirrors components/schemas/ComparisonRun."""

    model_config = ConfigDict(extra="forbid")

    run: RunOut
    facts: list[FactOut]


class ComparisonOut(BaseModel):
    """Mirrors components/schemas/Comparison."""

    model_config = ConfigDict(extra="forbid")

    items: list[ComparisonRunOut]


def _distinct(raw: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in raw:
        seen.setdefault(value.strip().lower(), None)
    return list(seen)


@router.get("", response_model=ComparisonOut)
def get_comparison(
    scope: OrganisationScoped,
    db: DbSession,
    request: Request,
    run_ids: Annotated[list[str], Query()],
) -> ComparisonOut:
    maximum: int = request.app.state.settings.comparison_max_profiles
    wanted = _distinct(run_ids)
    if not 2 <= len(wanted) <= maximum:
        raise InvalidField("run_ids", f"Choose between 2 and {maximum} different profiles.")
    # A malformed id is an unknown id; one that is not the caller's is the same 404.
    ids = list(dict.fromkeys(parse_resource_id(value) for value in wanted))
    found = {
        run.id: run for run in db.scalars(scope.select(ProfileRun).where(ProfileRun.id.in_(ids)))
    }
    if len(found) != len(ids):
        raise not_found()

    identities = {
        identity.id: identity
        for identity in db.scalars(
            select(SupplierIdentity).where(
                SupplierIdentity.organisation_id == scope.organisation_id,
                SupplierIdentity.id.in_({run.identity_id for run in found.values()}),
            )
        )
    }
    excluded = excluded_sources(db, scope.organisation_id, ids)
    proposed = proposed_counts(db, scope.organisation_id, ids)
    # A run that has not finished shows no facts: its column reads "run in progress".
    finished = [run_id for run_id, run in found.items() if run.status in FINISHED_STATUSES]
    stored: dict[uuid.UUID, dict[str, Fact]] = {run_id: {} for run_id in ids}
    for fact in db.scalars(scope.select(Fact).where(Fact.run_id.in_(finished))):
        stored[fact.run_id][fact.field] = fact
    emails = user_emails(
        db, scope, {fact.reviewed_by for facts in stored.values() for fact in facts.values()}
    )
    certsearch = load_extraction_settings().certsearch_url
    definition: ProfileDefinition = request.app.state.profile_definition
    hidden = hide_names(request, scope)

    items = []
    for run_id in ids:
        run = found[run_id]
        facts = [
            fact_out(stored[run_id][item.id], item.certification, certsearch, emails)
            for section in definition.sections
            for item in section.fields
            if item.kind == "fact" and item.id in stored[run_id]
        ]
        items.append(
            ComparisonRunOut(
                run=_run_out(
                    db,
                    scope,
                    run,
                    identities.get(run.identity_id),
                    hidden,
                    excluded.get(run_id, []),
                    proposed.get(run_id, 0),
                ),
                facts=facts,
            )
        )
    return ComparisonOut(items=items)
