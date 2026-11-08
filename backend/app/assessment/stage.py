"""The assessment stage of a run (spec Flow 1 step 5, F8; #25).

The structuring provider drafts the assessment of the run from its facts: SWOT points, risk
indicators and evidence gaps (prompt id `assessment`), then the procurement recommendations
(prompt id `recommendations`). Code keeps a statement only when it passes the rules of
`app.assessment.rules`; everything else is rejected and counted on the run.

Boundaries that hold here:
- `ask` is the single call site of the model for the assessment. The prompts come from the prompt
  set; the data part (facts, buyer context) passes the redaction gate before the request is built,
  and nothing but `RedactedText` is sent. The model has no tools: it returns an
  `AssessmentAnswer`; code makes the call and decides what is kept. A fact's value or quote is
  data inside fences, never an instruction, and nothing in the answer is executed.
- For an identity flagged `natural_person` nothing is requested and nothing is stored: the
  section reads "Not assessed: natural-person business".
- Facts of a field flagged `concerns_people` are not sent to the model, and a statement citing
  one is rejected anyway (the rule is in code, `rules.check`).
- Without buyer context the prompt carries no buyer-situation data, and code puts the
  first-evaluation assumption in front of every recommendation. With one (#26), the context the
  member entered reaches only the `recommendations` prompt, as redacted data inside fences, and
  states only what was entered.
- The financial evidence guidance (#26) is written by rules in code from the country table
  (`app.financial`), stored as an evidence-gap statement whose provider is `rules`; no model is
  called for it.
- Fit statements and the redrafting of the recommendations run later, in the worker, from a
  member's request (`app.assessment.drafting`); they use `ask` and `draft_part` below, so the
  gate, the validation, the provenance and the metering are the same.
- Prompt and completion text are never logged: counts and ids only.
- The stage can run again after a pause or a crash. The statements are written in one transaction
  together with the counts and the time of the draft, and a run with that time is skipped, so the
  draft is never duplicated and the counts are never counted twice.
- A provider outage raises `DependencyUnavailable("structuring_provider")`: the run pauses (#13).
"""

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from sqlalchemy import select

from app.assessment.rules import (
    BuyerContext,
    FactView,
    Kept,
    Tally,
    to_statement,
    validate,
)
from app.buyer.values import run_buyer_context, run_criteria
from app.collection.source_store import IdentityRedaction, identity_redaction
from app.db import Database, utc_now
from app.financial.guidance import (
    FINANCIAL_FIELDS,
    GUIDANCE_PROMPT_ID,
    GUIDANCE_PROVIDER,
    GUIDANCE_VERSION,
    Guidance,
    Observations,
    build_guidance,
    financial_year,
)
from app.financial.table import CountryTable
from app.limits.budget import RunBudgetExhausted
from app.llm_schemas import (
    ASSESSMENT_KINDS,
    FIT_KINDS,
    RECOMMENDATION_KINDS,
    AssessmentAnswer,
    AssessmentStatement,
)
from app.models import AssessmentItem, Fact, IdentitySession, ProfileRun, SupplierIdentity
from app.profile_definition import ProfileDefinition
from app.prompts import PromptSet, log_render
from app.providers import (
    ProviderError,
    Providers,
    StructuredOutputInvalid,
    StructuringClient,
    StructuringRequest,
)
from app.redaction import RedactionGate, gate_for
from app.runs.stages import DependencyUnavailable, Stage, StageContext, StageOutcome

logger = logging.getLogger(__name__)

ASSESSMENT_PROMPT: Final = "assessment"
RECOMMENDATIONS_PROMPT: Final = "recommendations"
FIT_PROMPT: Final = "fit"
ALLOWED_KINDS: Final = {
    ASSESSMENT_PROMPT: ASSESSMENT_KINDS,
    FIT_PROMPT: FIT_KINDS,
    RECOMMENDATIONS_PROMPT: RECOMMENDATION_KINDS,
}
NONE_ENTERED: Final = "None entered."
MAX_VALUE_CHARS: Final = 600


@dataclass(frozen=True)
class Provenance:
    provider: str
    model_id: str
    model_version: str  # the id of the approved configuration that pins the exact model
    prompt_id: str
    prompt_version: str
    generated_at: datetime


@dataclass(frozen=True)
class Draft:
    kept: Kept
    provenance: Provenance


@dataclass(frozen=True)
class RunData:
    drafted: bool
    natural_person: bool
    language: str
    facts: list[FactView]
    redaction: IdentityRedaction
    organisation_id: uuid.UUID
    country: str | None = None
    buyer_context: BuyerContext | None = None
    criteria: list[str] = field(default_factory=list)


def _line(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:MAX_VALUE_CHARS]


def facts_text(facts: list[FactView], labels: dict[str, str]) -> str:
    """The facts for the prompt: id, field, value and verbatim quote of each usable fact, then the
    fields with no public evidence (by field, without an id: nothing can cite them)."""
    lines = [
        f"- id={fact.id} | field={fact.field} ({labels.get(fact.field, fact.field)}) | "
        f'value={_line(fact.value)} | quote="{_line(fact.quote)}"'
        for fact in facts
        if fact.usable
    ]
    missing = [
        f"{fact.field} ({labels.get(fact.field, fact.field)})"
        for fact in facts
        if fact.status == "not_found" and not fact.concerns_people
    ]
    if missing:
        lines.append("No public evidence found for: " + ", ".join(missing))
    return "\n".join(lines) if lines else NONE_ENTERED


def prompts_to_request(natural_person: bool, facts: list[FactView]) -> list[str]:
    """The prompts the stage sends, in order. A natural-person business is not assessed: nothing
    is requested. The recommendations need a fact to cite, and a recommendation is asked after
    the assessment so that it can rest on it."""
    if natural_person or not facts:
        return []
    if any(fact.usable for fact in facts):
        return [ASSESSMENT_PROMPT, RECOMMENDATIONS_PROMPT]
    return [ASSESSMENT_PROMPT]


def assessed_text(drafts: list[Draft]) -> str:
    lines = [
        f"- {draft.kept.statement.kind}: {_line(draft.kept.text)} "
        f"(cites {', '.join(draft.kept.cited) or 'no fact'})"
        for draft in drafts
    ]
    return "\n".join(lines) if lines else NONE_ENTERED


def ask(
    context: StageContext,
    client: StructuringClient,
    gate: RedactionGate,
    redaction: IdentityRedaction,
    prompts: PromptSet,
    prompt_id: str,
    values: dict[str, str],
) -> tuple[list[AssessmentStatement], int]:
    """The single call site of the model for the assessment: the validated statements of the
    answer, and the number of items dropped as invalid (after one retry).

    `values` holds the data of the prompt (facts, buyer context); it passes through
    `RedactionGate.redact` before the request is built, like every text sent to a provider.
    """
    rendered = prompts.render(prompt_id, values)
    log_render(rendered)
    data = gate.redact(
        rendered.data,
        person_names=redaction.person_names,
        addresses=redaction.addresses,
        company_names=redaction.company_names,
    )
    request = StructuringRequest(instructions=rendered.instructions, data=data)
    valid: list[AssessmentStatement] = []
    invalid = 0
    for _ in range(1 + client.max_retries):  # a retry is a call: it counts against the budget
        context.check_stop()
        try:
            answer = client.structure(request, AssessmentAnswer, context.call_context)
        except StructuredOutputInvalid:
            return [], 1  # the whole answer was unusable after the client's retry
        valid, invalid = [], 0
        for raw in answer.statements:
            statement = to_statement(raw)
            if statement is None:
                invalid += 1
            else:
                valid.append(statement)
        if invalid == 0:
            break
    return valid, invalid


def prompt_values(
    prompts: PromptSet,
    prompt_id: str,
    language: str,
    facts: str,
    buyer_context: BuyerContext | None,
    assessed: str,
    criteria: str | None = None,
) -> dict[str, str]:
    """The values the prompt uses. Without buyer context, nothing about the buyer is sent; the
    criteria are sent to the `fit` prompt only (the caller passes none to the others)."""
    available = {
        "language": language,
        "facts": facts,
        "buyer_criteria": criteria or NONE_ENTERED,
        "buyer_context": buyer_context.text if buyer_context else NONE_ENTERED,
        "assessment": assessed,
    }
    return {name: available[name] for name in prompts.placeholders(prompt_id)}


def draft_part(
    context: StageContext,
    client: StructuringClient,
    gate: RedactionGate,
    redaction: IdentityRedaction,
    prompts: PromptSet,
    prompt_id: str,
    facts: list[FactView],
    labels: dict[str, str],
    language: str,
    buyer_context: BuyerContext | None,
    assessed: list[Draft],
    tally: Tally,
    criteria: str | None = None,
) -> list[Draft]:
    """One call (`assessment`, `fit` or `recommendations`), its answer validated by the rules."""
    values = prompt_values(
        prompts,
        prompt_id,
        language,
        facts_text(facts, labels),
        buyer_context,
        assessed_text(assessed),
        criteria,
    )
    statements, invalid = _ask_safely(context, client, gate, redaction, prompts, prompt_id, values)
    generated_at = utc_now()
    tally.invalid += invalid
    by_id = {fact.id.lower(): fact for fact in facts}
    kept = validate(statements, ALLOWED_KINDS[prompt_id], by_id, buyer_context, language, tally)
    provenance = Provenance(
        provider=client.provider,
        model_id=client.model_id,
        model_version=client.config_id,
        prompt_id=prompt_id,
        prompt_version=prompts.prompts[prompt_id].version,
        generated_at=generated_at,
    )
    return [Draft(item, provenance) for item in kept]


def fit_requested(natural_person: bool, facts: list[FactView], criteria: str | None) -> bool:
    """Whether a fit call is made: criteria were entered, the identity is not a natural person and
    there is a fact to cite. With no criteria the section reads "Enter your criteria to assess
    fit" and no model is called."""
    return bool(criteria) and not natural_person and any(fact.usable for fact in facts)


def make_assessment_stage(
    definition: ProfileDefinition, prompts: PromptSet, table: CountryTable | None = None
) -> Stage:
    people = {item.id for item in definition.fields() if item.concerns_people}

    def stage(context: StageContext) -> StageOutcome | None:
        database = context.database
        data = load_run(database, context.run_id, people)
        if data is None or data.drafted:
            return None
        requested = prompts_to_request(data.natural_person, data.facts)
        tally = Tally()
        drafts: list[Draft] = []
        unfinished: list[str] = []  # the parts the run budget (#30) did not allow
        if requested:
            client = structuring_client(context.providers)
            gate = gate_for(database)
            labels = {
                item.id: item.labels.get(data.language, item.id) for item in definition.fields()
            }
            for prompt_id in requested:
                try:
                    drafts += draft_part(
                        context,
                        client,
                        gate,
                        data.redaction,
                        prompts,
                        prompt_id,
                        data.facts,
                        labels,
                        data.language,
                        # SWOT is about the supplier; only the recommendations take the context.
                        data.buyer_context if prompt_id == RECOMMENDATIONS_PROMPT else None,
                        drafts,
                        tally,
                    )
                except RunBudgetExhausted:
                    unfinished = requested[requested.index(prompt_id) :]
                    break
        elif data.natural_person:
            return None  # not assessed: nothing requested, nothing stored
        # The parts that need no more work: drafted, or not requested at all.
        done = frozenset({ASSESSMENT_PROMPT, RECOMMENDATIONS_PROMPT} - set(unfinished))
        if unfinished and not drafts:
            raise RunBudgetExhausted(done)  # nothing drafted: nothing to keep
        guidance = None
        if table is not None:
            guidance = build_guidance(
                table,
                data.country,
                data.language,
                financial_year(utc_now().date()),
                data.natural_person,
                Observations(collected=collected_documents(data.facts)),
            )
        _store(context, drafts, tally, guidance, table)
        if unfinished:
            raise RunBudgetExhausted(done)  # what was drafted is stored; the run ends `partial`
        return None

    return stage


def collected_documents(facts: list[FactView]) -> frozenset[str]:
    """The document types backed by a kept financial fact of the run."""
    return frozenset(
        FINANCIAL_FIELDS[fact.field]
        for fact in facts
        if fact.usable
        and fact.field in FINANCIAL_FIELDS
        # The supplier's own claim is not a filed statement (#134): it does not clear the gap.
        and fact.source_type != "supplier_claim"
    )


def structuring_client(providers: Providers | None) -> StructuringClient:
    if providers is None:
        raise DependencyUnavailable("structuring_provider")
    try:
        return providers.structuring()
    except ProviderError:
        logger.warning("The structuring provider is not usable")
        raise DependencyUnavailable("structuring_provider") from None


def _ask_safely(
    context: StageContext,
    client: StructuringClient,
    gate: RedactionGate,
    redaction: IdentityRedaction,
    prompts: PromptSet,
    prompt_id: str,
    values: dict[str, str],
) -> tuple[list[AssessmentStatement], int]:
    try:
        return ask(context, client, gate, redaction, prompts, prompt_id, values)
    except ProviderError as error:
        # An outage (StructuredOutputInvalid is handled in `ask`): the run pauses and resumes.
        logger.warning("Structuring provider call failed: %s", type(error).__name__)
        raise DependencyUnavailable("structuring_provider") from None


def load_run(database: Database, run_id: uuid.UUID, people: set[str]) -> RunData | None:
    with database.session() as db:
        run = db.get(ProfileRun, run_id)
        if run is None:
            return None
        identity = db.scalar(select(SupplierIdentity).where(SupplierIdentity.id == run.identity_id))
        language = db.scalar(
            select(IdentitySession.profile_language)
            .where(IdentitySession.identity_id == run.identity_id)
            .order_by(IdentitySession.created_at.desc())
            .limit(1)
        )
        rows = db.scalars(
            select(Fact).where(Fact.run_id == run_id).order_by(Fact.section, Fact.field)
        )
        facts = [
            FactView(
                id=str(row.id),
                field=row.field,
                status=row.status,
                value=row.value,
                quote=row.quote,
                concerns_people=row.field in people,
                source_type=row.source_type,
            )
            for row in rows
        ]
        return RunData(
            drafted=run.assessment_drafted_at is not None,
            natural_person=bool(identity and identity.natural_person),
            language=language or "en",
            facts=facts,
            redaction=identity_redaction(db, run_id),
            organisation_id=run.organisation_id,
            country=identity.country if identity else None,
            buyer_context=run_buyer_context(db, run_id),
            criteria=run_criteria(db, run_id),
        )


def _store(
    context: StageContext,
    drafts: list[Draft],
    tally: Tally,
    guidance: Guidance | None = None,
    table: CountryTable | None = None,
) -> None:
    """One transaction: the statements, the counts and the time of the draft, or nothing."""
    with context.database.session() as db:
        run = db.scalar(select(ProfileRun).where(ProfileRun.id == context.run_id).with_for_update())
        if run is None or run.assessment_drafted_at is not None:
            return  # another execution stored the draft first: counted there, not twice
        for position, draft in enumerate(drafts):
            statement, provenance = draft.kept.statement, draft.provenance
            db.add(
                AssessmentItem(
                    run_id=context.run_id,
                    organisation_id=context.organisation_id,
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
                    generated_at=provenance.generated_at,
                    status="ai_draft",
                )
            )
        if guidance is not None and table is not None:
            # Written by rules in code: no provider, no model, no prompt (provenance "rules").
            db.add(
                AssessmentItem(
                    run_id=context.run_id,
                    organisation_id=context.organisation_id,
                    position=len(drafts),
                    kind="evidence_gap",
                    text=guidance.message,
                    cited_fact_ids=[],
                    cites_buyer_context=False,
                    gap_evidence=guidance.gap_evidence,
                    buyer_context_version=None,
                    guidance=guidance.to_json(),
                    provider=GUIDANCE_PROVIDER,
                    model_id=GUIDANCE_PROVIDER,
                    model_version=table.content_hash,
                    prompt_id=GUIDANCE_PROMPT_ID,
                    prompt_version=GUIDANCE_VERSION,
                    generated_at=utc_now(),
                    status="ai_draft",
                )
            )
        run.rejected_statements += tally.rejected
        run.invalid_items += tally.invalid
        run.assessment_drafted_at = utc_now()
        db.commit()
    logger.info(
        "Assessment for run %s: %d statements kept, %d rejected, %d invalid items",
        context.run_id,
        len(drafts),
        tally.rejected,
        tally.invalid,
    )
