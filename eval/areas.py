"""The four areas: how a case is run, and what is measured. No database, no network.

Every model call goes through the production code path: identity through `IdentityAgent` (#16),
extraction through `ask` and `judge` of the extraction stage (#23), assessment through
`draft_part` of the assessment stage (#25), retrieval through `make_retriever` (#20), all with
the #11 clients, the #55 prompt set and the #19 redaction gate.
A case that hits a provider error is marked "error" and the others continue.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from app.assessment.rules import ASSUMPTION, BuyerContext, FactView
from app.assessment.rules import Tally as AssessmentTally
from app.assessment.stage import Draft, draft_part, fit_requested, prompts_to_request
from app.collection.retrieval import IdentityRecord, make_retriever
from app.collection.source_store import IdentityRedaction
from app.db import Database
from app.extraction.grounding import normalise, quote_in_text
from app.extraction.settings import ExtractionSettings
from app.extraction.stage import (
    SourceText,
    Tally,
    chunks,
    judge,
)
from app.extraction.stage import (
    ask as extraction_ask,
)
from app.http_client import GuardedClient
from app.identity.agent import IdentityAgent
from app.identity.services import AsyncRunner, IdentityServices
from app.llm_schemas import RECOMMENDATION_KINDS
from app.models import IdentitySession
from app.profile_definition import FieldDefinition, ProfileDefinition
from app.prompts import PromptSet
from app.providers.interface import RetrievedUrl
from app.providers.metering import CallContext
from app.redaction import RedactionGate
from app.registries import RegistryCandidate, RegistrySearchQuery, RegistrySearchResult
from app.registries.ranking import rank_candidates
from app.runs.stages import StageContext
from eval.backends import Backend
from eval.cases import AssessmentCase, CaseSet, ExtractionCase

ORGANISATION = uuid.UUID("00000000-0000-4000-8000-0000000000e1")
FETCHED = datetime(2026, 11, 5, tzinfo=UTC)
MAX_EXCHANGES = 3  # identity: the right company within this many exchanges


class ProviderFailure(Exception):
    """The provider failed during the case (the agent turned it into an error turn)."""


@dataclass
class CaseResult:
    case_id: str
    status: str  # "ok" | "error"
    # What the metrics are computed from (area specific counts).
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class Context:
    backend: Backend
    prompts: PromptSet
    gate: RedactionGate
    definition: ProfileDefinition


# --- identity --------------------------------------------------------------------------------

_CANDIDATE_DEFAULTS: dict[str, Any] = {"registries": ["gleif"], "lei": "529900EVAL00000000AA"}


class RecordedRegistries:
    """The registry answer recorded in the case; the real ranking applies when the case says so."""

    def __init__(self, registry: dict[str, Any]) -> None:
        self.candidates = [
            RegistryCandidate.model_validate({**_CANDIDATE_DEFAULTS, **fields})
            for fields in registry["candidates"]
        ]
        self.rank = bool(registry.get("rank"))

    async def search(self, query: RegistrySearchQuery) -> RegistrySearchResult:
        ordered = rank_candidates(query, self.candidates) if self.rank else self.candidates
        return RegistrySearchResult(
            candidates=tuple(ordered), failed_registries=(), website_fallback_offered=False
        )


def run_identity(case: dict[str, Any], context: Context) -> CaseResult:
    """Metrics: the confirmed company is the one proposed within three exchanges; no registry
    candidate is missing from the session after a search (a hint ranks, it never removes)."""
    registries = RecordedRegistries(case["registry"])
    recorded = [
        json.dumps(step["model_output"]) for step in case["steps"] if "model_output" in step
    ]
    providers = context.backend.providers(structuring=recorded)
    runner = AsyncRunner()
    http = GuardedClient()
    try:
        agent = IdentityAgent(
            context.prompts,
            providers,
            IdentityServices(registries=registries, runner=runner, http=http),
            context.gate,
        )
        language = case.get("language", "en")
        session = IdentitySession(
            organisation_id=ORGANISATION,
            name=case["input"]["name"],
            hints=dict(case["input"].get("hints", {})),
            profile_language=language,
            ui_language=language,
            transcript=[],
            candidates=[],
            registries={},
        )
        exchanges = 0
        counts = {"confirmations": 0, "right_company": 0, "candidates_kept": 0}
        dropped = 0
        for step in case["steps"]:
            if step["op"] == "create":
                agent.start(session)
                exchanges += 1
            elif step["op"] == "message":
                agent.correct(session, step["text"])
                exchanges += 1
            elif step["op"] == "confirm":
                counts["confirmations"] = 1
                if session.current_candidate_id == step["candidate_id"] and exchanges <= (
                    MAX_EXCHANGES
                ):
                    counts["right_company"] = 1
                continue
            if any(turn["kind"] == "error" for turn in session.transcript):
                raise ProviderFailure("the identity agent could not get an answer")
            shown = {entry["candidate"]["legal_name"] for entry in session.candidates}
            dropped += len({c.legal_name or c.name for c in registries.candidates} - shown)
        counts["candidates_kept"] = int(dropped == 0)
        return CaseResult(case["id"], "ok", counts)
    finally:
        runner.close()
        http.close()


# --- extraction ------------------------------------------------------------------------------


def _stage_context(providers_for: Callable[[], Any]) -> StageContext:
    """Only `check_stop` and `call_context` of the context are used by `ask`: no database here."""
    return StageContext(
        run_id=uuid.UUID(int=1),
        organisation_id=ORGANISATION,
        stage="extraction",
        database=cast(Database, None),
        providers=providers_for(),
        check_stop=lambda: None,
    )


def run_extraction(case: ExtractionCase, context: Context) -> CaseResult:
    """The loop of the extraction stage over the case's sources, without the database."""
    by_id = {item.id: item for item in context.definition.fields()}
    unknown = [name for name in case.fields if name not in by_id or by_id[name].kind != "fact"]
    if unknown:
        raise ValueError(f"case {case.id!r}: not a fact field of the profile definition: {unknown}")
    providers = context.backend.providers(structuring=[json.dumps(a) for a in case.recorded])
    client = providers.structuring()
    stage = _stage_context(lambda: providers)
    limits = ExtractionSettings()
    sources = [
        SourceText(
            id=uuid.UUID(item.id),
            url=item.url,
            fetched_at=FETCHED,
            author=None,
            text=item.text,
            source_type="other",
            publisher=item.url,
            normalised=normalise(item.text),
        )
        for item in case.sources
    ]
    pending: list[FieldDefinition] = [by_id[name] for name in case.fields]
    kept: dict[str, tuple[str, str, SourceText]] = {}
    tally = Tally()
    for source in sources:
        for chunk in chunks(source.text, limits.max_input_chars):
            if not pending:
                break
            wanted = {item.id: item for item in pending}
            answered, dropped = extraction_ask(
                stage,
                client,
                context.gate,
                IdentityRedaction(),
                context.prompts,
                source,
                chunk,
                pending,
            )
            tally.invalid_items += dropped
            for item in answered:
                if item.status != "found" or item.field in kept:
                    continue
                result = judge(item, source, tally, wanted, limits)
                if result is not None:
                    kept[item.field] = (result.value, result.quote, source)
            pending = [item for item in pending if item.id not in kept]
    counts = {
        "kept": len(kept),
        # Measured here again, not taken from the stage's own check.
        "quotes_in_source": sum(
            quote_in_text(quote, source.normalised) for _value, quote, source in kept.values()
        ),
        "correct": 0,
        "expected_found": 0,
        "expected_found_kept": 0,
        "expected_not_found": 0,
        "invented": 0,
        "grounding_discarded": tally.grounding_failures,
        "invalid_dropped": tally.invalid_items,
    }
    notes = []
    if tally.grounding_failures:
        notes.append(f"{tally.grounding_failures} value(s) discarded by the grounding check")
    if tally.invalid_items:
        notes.append(f"{tally.invalid_items} invalid item(s) dropped")
    for name, accepted in case.expected.items():
        got = kept.get(name)
        if accepted is None:
            counts["expected_not_found"] += 1
            if got is not None:
                counts["invented"] += 1
                notes.append(f"{name}: a value was kept where the sources hold none")
            continue
        counts["expected_found"] += 1
        if got is None:
            notes.append(f"{name}: not found")
            continue
        counts["expected_found_kept"] += 1
        if normalise(got[0]).casefold() in {normalise(v).casefold() for v in accepted}:
            counts["correct"] += 1
        else:
            notes.append(f"{name}: wrong value")
    return CaseResult(case.id, "ok", counts, notes)


# --- assessment ------------------------------------------------------------------------------


def run_assessment(case: AssessmentCase, context: Context) -> CaseResult:
    """One case through the production path of the assessment stage, without the database: the
    prompts the stage would send (none for a natural-person business), the call, the rules."""
    by_id = {item.id: item for item in context.definition.fields()}
    unknown = [item.field for item in case.facts if item.field not in by_id]
    if unknown:
        raise ValueError(f"case {case.id!r}: not a field of the profile definition: {unknown}")
    facts = [
        FactView(
            id=item.id,
            field=item.field,
            status=item.status,
            value=item.value or None,
            quote=item.quote or None,
            concerns_people=by_id[item.field].concerns_people,
        )
        for item in case.facts
    ]
    natural_person = case.kind == "natural_person"
    wanted = {"statement": "assessment", "recommendation": "recommendations"}.get(case.kind)
    requested = [name for name in prompts_to_request(natural_person, facts) if name == wanted]
    criteria = case.buyer_criteria.strip() or None
    if case.kind == "fit" and fit_requested(natural_person, facts, criteria):
        requested = ["fit"]  # no criteria: no call, as in production
    # Fit is drafted against the criteria only: the buyer context is never sent to it.
    buyer = (
        BuyerContext(1, case.buyer_context)
        if case.buyer_context is not None and case.kind != "fit"
        else None
    )
    tally = AssessmentTally()
    drafts: list[Draft] = []
    if requested:
        recorded = [json.dumps({"statements": call}) for call in case.recorded]
        providers = context.backend.providers(structuring=recorded)
        drafts = draft_part(
            _stage_context(lambda: providers),
            providers.structuring(),
            context.gate,
            IdentityRedaction(),
            context.prompts,
            requested[0],
            facts,
            {item.id: item.labels["en"] for item in context.definition.fields()},
            "en",
            buyer,
            [],
            tally,
            criteria if requested[0] == "fit" else None,
        )
    return _assessment_counts(case, facts, drafts, buyer, tally, requested)


def _assessment_counts(
    case: AssessmentCase,
    facts: list[FactView],
    drafts: list[Draft],
    buyer: BuyerContext | None,
    tally: AssessmentTally,
    requested: list[str],
) -> CaseResult:
    usable = {item.id.lower() for item in facts if item.usable}
    allowed = {value.lower() for value in case.expected.cited_fact_ids} or usable
    notes = []
    counts = {
        "kept": 0,
        "cite_valid": 0,
        "recommendations": 0,
        "recommendations_without_context": 0,
        "with_assumption": 0,
        "claims_unentered_context": 0,
        "natural_person_cases": int(case.kind == "natural_person"),
        "natural_person_clean": 0,
        "kept_with_forbidden_phrase": 0,
        "fit_cases": int(case.kind == "fit"),
        "fit_calls_without_criteria": 0,
    }
    for draft in drafts:
        statement, cited = draft.kept.statement, set(draft.kept.cited)
        counts["kept"] += 1
        # Measured here again, not taken from the rules' own check.
        gap_ok = statement.kind == "evidence_gap" and bool((statement.gap_evidence or "").strip())
        if cited <= (allowed & usable) and (cited or gap_ok):
            counts["cite_valid"] += 1
        else:
            notes.append(f"{statement.kind}: cites {sorted(cited - allowed) or 'no fact'}")
        if statement.kind in RECOMMENDATION_KINDS:
            counts["recommendations"] += 1
            if buyer is None:
                counts["recommendations_without_context"] += 1
                if draft.kept.text.startswith(tuple(ASSUMPTION.values())):
                    counts["with_assumption"] += 1
                if statement.cites_buyer_context:
                    counts["claims_unentered_context"] += 1
    forbidden = [phrase.casefold() for phrase in case.expected.must_not_contain]
    counts["kept_with_forbidden_phrase"] = sum(
        any(phrase in draft.kept.text.casefold() for phrase in forbidden) for draft in drafts
    )
    if case.kind == "fit" and requested and not case.buyer_criteria.strip():
        counts["fit_calls_without_criteria"] = 1
    if case.expected.no_call and (requested or drafts):
        notes.append("a call was made although no criteria were entered")
    if case.kind == "natural_person":
        counts["natural_person_clean"] = int(not requested and not drafts)
    if tally.rejected:
        notes.append(f"{tally.rejected} statement(s) rejected by the rules")
    if tally.invalid:
        notes.append(f"{tally.invalid} invalid item(s) dropped")
    if case.expected.no_recommendation and counts["recommendations"]:
        notes.append("a recommendation was kept for a natural-person business")
    if case.expected.cites_buyer_context and not any(
        draft.kept.statement.cites_buyer_context for draft in drafts
    ):
        notes.append("no kept statement rests on the buyer context")
    return CaseResult(case.id, "ok", counts, notes)


# --- retrieval -------------------------------------------------------------------------------


def run_retrieval(case: dict[str, Any], context: Context) -> CaseResult:
    """Metric: the share of returned addresses that can be verified."""
    recorded = [RetrievedUrl(**item) for item in case["provider_urls"]]
    providers = context.backend.providers(retrieval=[recorded])
    retrieve = make_retriever(
        providers,
        context.prompts,
        context.gate,
        IdentityRedaction(company_names=(case["legal_name"],)),
        IdentityRecord(case["legal_name"], None, None),
        CallContext(organisation_id=ORGANISATION),
    )
    returned = retrieve(list(case["lacking"]))
    verifier = context.backend.verifier()
    try:
        reachable = set(case["pages"])
        verified = sum(verifier.verified(url, reachable) for url in returned)
    finally:
        verifier.close()
    return CaseResult(case["id"], "ok", {"returned": len(returned), "verified": verified})


def case_set_sizes(cases: CaseSet) -> dict[str, int]:
    return {
        "identity": len(cases.identity),
        "extraction": len(cases.extraction),
        "assessment": len(cases.assessment),
        "retrieval": len(cases.retrieval),
    }
