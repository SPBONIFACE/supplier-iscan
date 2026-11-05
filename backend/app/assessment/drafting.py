"""Fit statements and the redrafting of the recommendations, on a member's request (#26).

`POST /runs/{id}/fit` and `POST /runs/{id}/recommendations` queue a job; the worker runs
`run_draft_job`. It reuses the assessment stage: the same `draft_part` (prompt from the prompt set,
the data through the redaction gate in `ask`, metering through the call context), the same rules
(`app.assessment.rules`), the same provenance. What differs:

- `fit` is drafted against the member's criteria only, and only when criteria are stored: with
  none, no model is called. The buyer context is not sent to it.
- `recommendations` take the current buyer context, or the first-evaluation assumption when none
  is stored; each kept recommendation stores the version of the context it used.
- A redraft replaces the earlier `ai_draft` statements of its prompt and never a reviewed one: a
  recommendation kind that a member has approved or corrected is not drafted again. When the model
  returns nothing usable, the earlier drafts stay.
- A natural-person business, or a run whose assessment is not drafted yet, is not touched.
- Nothing is logged but counts and ids.
"""

import logging
import uuid
from collections.abc import Callable
from typing import Final

from sqlalchemy import delete, func, select

from app.assessment.rules import ONCE_ONLY, Kept, Tally
from app.assessment.stage import (
    FIT_PROMPT,
    RECOMMENDATIONS_PROMPT,
    Draft,
    Provenance,
    draft_part,
    fit_requested,
    load_run,
    structuring_client,
)
from app.buyer.values import criteria_prompt_text
from app.db import Database, utc_now
from app.llm_schemas import ASSESSMENT_KINDS, AssessmentStatement
from app.models import AssessmentItem, ProfileRun
from app.profile_definition import ProfileDefinition
from app.prompts import PromptSet
from app.providers import Providers
from app.redaction import gate_for
from app.runs.stages import StageContext

logger = logging.getLogger(__name__)

ASSESSMENT_JOB: Final = "assessment_part"  # the kind of the queue job that drafts one part
PARTS: Final = (FIT_PROMPT, RECOMMENDATIONS_PROMPT)
REVIEWED: Final = ("approved", "corrected")


def _assessed(database: Database, run_id: uuid.UUID) -> list[Draft]:
    """The SWOT points, risk indicators and gaps drafted for the run (not the guidance written
    by rules), as the recommendations prompt shows them."""
    with database.session() as db:
        rows = db.scalars(
            select(AssessmentItem)
            .where(
                AssessmentItem.run_id == run_id,
                AssessmentItem.kind.in_(ASSESSMENT_KINDS),
                AssessmentItem.status != "deleted",
                AssessmentItem.provider != "rules",
            )
            .order_by(AssessmentItem.position)
        )
        return [
            Draft(
                Kept(
                    AssessmentStatement(
                        kind=row.kind,  # type: ignore[arg-type]  # constrained by the table
                        text=row.text,
                    ),
                    tuple(str(value) for value in row.cited_fact_ids),
                    row.text,
                    row.buyer_context_version,
                ),
                Provenance(
                    row.provider,
                    row.model_id,
                    row.model_version,
                    row.prompt_id,
                    row.prompt_version,
                    row.generated_at,
                ),
            )
            for row in rows
        ]


def run_draft_job(
    database: Database,
    providers: Providers | None,
    definition: ProfileDefinition,
    prompts: PromptSet,
    run_id: uuid.UUID,
    part: str,
    beat: Callable[[], None],
) -> None:
    """Draft `part` ("fit" or "recommendations") for the run and store it. Raises
    `DependencyUnavailable` when the provider is down: the member asks again."""
    if part not in PARTS:
        raise ValueError(f"unknown part {part!r}")
    people = {item.id for item in definition.fields() if item.concerns_people}
    data = load_run(database, run_id, people)
    if data is None or not data.drafted or data.natural_person:
        return  # nothing to redraft, or not assessed: nothing requested, nothing stored
    criteria = criteria_prompt_text(data.criteria)
    if part == FIT_PROMPT:
        if not fit_requested(data.natural_person, data.facts, criteria):
            return  # "Enter your criteria to assess fit": no model is called
    elif not any(fact.usable for fact in data.facts):
        return
    context = StageContext(run_id, data.organisation_id, "assessment", database, providers, beat)
    labels = {item.id: item.labels.get(data.language, item.id) for item in definition.fields()}
    tally = Tally()
    drafts = draft_part(
        context,
        structuring_client(providers),
        gate_for(database),
        data.redaction,
        prompts,
        part,
        data.facts,
        labels,
        data.language,
        data.buyer_context if part == RECOMMENDATIONS_PROMPT else None,
        _assessed(database, run_id) if part == RECOMMENDATIONS_PROMPT else [],
        tally,
        criteria if part == FIT_PROMPT else None,
    )
    _store_part(database, run_id, data.organisation_id, part, drafts, tally)


def _store_part(
    database: Database,
    run_id: uuid.UUID,
    organisation_id: uuid.UUID,
    part: str,
    drafts: list[Draft],
    tally: Tally,
) -> None:
    """One transaction: the new drafts replace the earlier `ai_draft` ones of this part, and the
    counts are added."""
    with database.session() as db:
        run = db.scalar(select(ProfileRun).where(ProfileRun.id == run_id).with_for_update())
        if run is None:
            return
        run.rejected_statements += tally.rejected
        run.invalid_items += tally.invalid
        if drafts:
            reviewed = set(
                db.scalars(
                    select(AssessmentItem.kind).where(
                        AssessmentItem.run_id == run_id,
                        AssessmentItem.prompt_id == part,
                        AssessmentItem.status.in_(REVIEWED),
                    )
                )
            )
            db.execute(
                delete(AssessmentItem).where(
                    AssessmentItem.run_id == run_id,
                    AssessmentItem.prompt_id == part,
                    AssessmentItem.status == "ai_draft",
                )
            )
            position = (
                db.scalar(
                    select(func.max(AssessmentItem.position)).where(AssessmentItem.run_id == run_id)
                )
                or 0
            )
            for draft in drafts:
                statement, provenance = draft.kept.statement, draft.provenance
                if statement.kind in ONCE_ONLY and statement.kind in reviewed:
                    continue  # a member's decision is never replaced
                position += 1
                db.add(
                    AssessmentItem(
                        run_id=run_id,
                        organisation_id=organisation_id,
                        position=position,
                        kind=statement.kind,
                        text=draft.kept.text,
                        level=statement.level,
                        label=statement.label,
                        timing=(statement.timing or "").strip() or None,
                        cited_fact_ids=list(draft.kept.cited),
                        cites_buyer_context=statement.cites_buyer_context,
                        gap_evidence=(statement.gap_evidence or "").strip() or None,
                        buyer_context_version=draft.kept.buyer_context_version,
                        provider=provenance.provider,
                        model_id=provenance.model_id,
                        model_version=provenance.model_version,
                        prompt_id=provenance.prompt_id,
                        prompt_version=provenance.prompt_version,
                        generated_at=provenance.generated_at or utc_now(),
                        status="ai_draft",
                    )
                )
        db.commit()
    logger.info(
        "Redraft %s for run %s: %d statements kept, %d rejected, %d invalid items",
        part,
        run_id,
        len(drafts),
        tally.rejected,
        tally.invalid,
    )
