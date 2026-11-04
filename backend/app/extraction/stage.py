"""The extraction stage of a run (spec Flow 1 step 4, F3; #23 and #24).

The structuring provider fills the `fact` fields of the profile definition from the stored
(redacted) text of the run's sources. Code keeps a value only when it passes the grounding check
(`app.extraction.grounding`); everything else is discarded and counted on the run.

Boundaries that hold here:
- `ask` is the single call site of the model for extraction. The prompt comes from the prompt set
  (id `extraction`); the data part passes the redaction gate again before the request is built
  (see `ask`), so a name added to the suppression list after collection is also redacted, and
  nothing but `RedactedText` is sent. The model has no tools: it returns a `FieldExtractionAnswer`,
  and code makes the call and decides what is kept.
- Only `fact` fields are requested, never `assessment` or `buyer` fields.
- Prompt and completion text are never logged: counts and ids only.
- The stage can run again after a pause or a crash. A section's facts are written in one
  transaction together with its counts, and a section with stored facts is skipped, so there is
  one fact per run and field and the counts are never counted twice.
- A provider outage raises `DependencyUnavailable("structuring_provider")`: the run pauses (#13).
"""

import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from pydantic import ValidationError
from sqlalchemy import select

from app.collection.source_store import IdentityRedaction, identity_redaction
from app.db import Database
from app.extraction.grounding import (
    MAX_QUOTE_CHARS,
    is_redacted_quote,
    normalise,
    quote_in_text,
    quote_long_enough,
    value_supported,
)
from app.extraction.settings import ExtractionSettings, load_extraction_settings
from app.extraction.source_type import classify_source, host_of, registry_domains
from app.llm_schemas import FieldExtraction, FieldExtractionAnswer
from app.models import Fact, ProfileRun, Source, SupplierIdentity
from app.profile_definition import FieldDefinition, ProfileDefinition
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

PROMPT_ID: Final = "extraction"
ATTEMPTS: Final = 2  # one retry when an item does not match the schema


@dataclass(frozen=True)
class SourceText:
    """A stored source, with what extraction derives from it once."""

    id: uuid.UUID
    url: str
    fetched_at: datetime
    author: str | None
    text: str
    source_type: str
    publisher: str
    normalised: str = field(repr=False)


@dataclass(frozen=True)
class Kept:
    value: str
    quote: str
    quote_redacted: bool
    source: SourceText


@dataclass
class Tally:
    grounding_failures: int = 0
    invalid_items: int = 0


def chunks(text: str, size: int) -> Iterator[str]:
    """`text` in pieces of at most `size` characters, cut at a line or a word when there is one in
    the second half of the piece (CJK text has none and is cut where the size ends)."""
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(text.rfind("\n", start, end), text.rfind(" ", start, end))
            if cut > start + size // 2:
                end = cut
        yield text[start:end]
        start = end


def fields_text(fields: list[FieldDefinition]) -> str:
    return "\n".join(f"- {item.id}: {item.extraction_hint}" for item in fields)


def groups_of(definition: ProfileDefinition) -> list[tuple[str, list[FieldDefinition]]]:
    """The field groups: the sections of the definition, with their `fact` fields only."""
    groups = []
    for section in definition.sections:
        facts = [item for item in section.fields if item.kind == "fact"]
        if facts:
            groups.append((section.id, facts))
    return groups


def judge(
    item: FieldExtraction,
    source: SourceText,
    tally: Tally,
    requested: dict[str, FieldDefinition],
    limits: ExtractionSettings | None = None,
) -> Kept | None:
    """The grounding check of one `found` item, counted on `tally` when it is discarded."""
    if (
        item.field not in requested
        or item.value is None
        or item.quote is None
        or item.source_id is None
    ):
        tally.invalid_items += 1  # not a field that was asked for: not an answer to the request
        return None
    quote = item.quote.strip()
    limits = limits or ExtractionSettings()
    if (
        item.source_id.strip() != str(source.id)  # a source that is not the one given
        or len(quote) > MAX_QUOTE_CHARS
        or not quote_in_text(quote, source.normalised)
        or not quote_long_enough(quote, limits.min_quote_chars, limits.min_quote_chars_cjk)
    ):
        tally.grounding_failures += 1
        return None
    if not value_supported(item.value, quote):  # a guard on figures: counted as invalid
        tally.invalid_items += 1
        return None
    return Kept(item.value.strip(), quote, is_redacted_quote(quote), source)


def ask(
    context: StageContext,
    client: StructuringClient,
    gate: RedactionGate,
    redaction: IdentityRedaction,
    prompts: PromptSet,
    source: SourceText,
    chunk: str,
    requested: list[FieldDefinition],
) -> tuple[list[FieldExtraction], int]:
    """The single call site of the model for extraction: the validated items of the answer, and
    the number of items dropped as invalid (after one retry).

    The source text is already redacted in `Source.redacted_text`. It still goes through
    `RedactionGate.redact` before the request is built, like every text sent to a provider: the
    gate is the only way to obtain the `RedactedText` the provider interface accepts, and it is
    idempotent on `[…]`. It also applies a suppression-list entry added after collection.
    """
    rendered = prompts.render(
        PROMPT_ID,
        {"fields": fields_text(requested), "source_id": str(source.id), "source_text": chunk},
    )
    log_render(rendered)
    data = gate.redact(
        rendered.data,
        person_names=redaction.person_names,
        addresses=redaction.addresses,
        company_names=redaction.company_names,
    )
    request = StructuringRequest(instructions=rendered.instructions, data=data)
    valid: list[FieldExtraction] = []
    invalid = 0
    for _ in range(ATTEMPTS):
        context.check_stop()
        try:
            answer = client.structure(request, FieldExtractionAnswer, context.call_context)
        except StructuredOutputInvalid:
            # The whole answer was unusable after the client's retry: every item is lost.
            return [], len(requested)
        valid, invalid = [], 0
        for raw in answer.extractions:
            try:
                valid.append(FieldExtraction.model_validate(raw.model_dump()))
            except ValidationError:
                invalid += 1
        if invalid == 0:
            break
    return valid, invalid


def make_extraction_stage(
    definition: ProfileDefinition,
    prompts: PromptSet,
    settings: ExtractionSettings | None = None,
) -> Stage:
    limits = settings or load_extraction_settings()
    groups = groups_of(definition)

    def stage(context: StageContext) -> StageOutcome | None:
        database = context.database
        sources, redaction = _load(database, context.run_id)
        with database.session() as db:
            stored = set(db.scalars(select(Fact.field).where(Fact.run_id == context.run_id)))
        todo = [(name, items) for name, items in groups if any(i.id not in stored for i in items)]
        if not todo:
            return None
        client: StructuringClient | None = None
        gate = gate_for(database)
        for section_id, items in todo:
            tally = Tally()
            kept: dict[str, Kept] = {}
            pending = list(items)
            for source in sources:
                if not pending:
                    break
                for chunk in chunks(source.text, limits.max_input_chars):
                    if not pending:
                        break
                    if client is None:
                        client = _client(context.providers)
                    wanted = {item.id: item for item in pending}
                    answered, dropped = _ask_safely(
                        context, client, gate, redaction, prompts, source, chunk, pending
                    )
                    tally.invalid_items += dropped
                    for item in answered:
                        if item.status != "found" or item.field in kept:
                            continue
                        result = judge(item, source, tally, wanted, limits)
                        if result is not None:
                            kept[item.field] = result
                    pending = [i for i in pending if i.id not in kept]
            _store(context, section_id, items, kept, tally)
        return None

    return stage


def _client(providers: Providers | None) -> StructuringClient:
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
    source: SourceText,
    chunk: str,
    pending: list[FieldDefinition],
) -> tuple[list[FieldExtraction], int]:
    try:
        return ask(context, client, gate, redaction, prompts, source, chunk, pending)
    except ProviderError as error:
        # An outage (StructuredOutputInvalid is handled in `ask`): the run pauses and resumes.
        logger.warning("Structuring provider call failed: %s", type(error).__name__)
        raise DependencyUnavailable("structuring_provider") from None


def _load(database: Database, run_id: uuid.UUID) -> tuple[list[SourceText], IdentityRedaction]:
    with database.session() as db:
        run = db.get(ProfileRun, run_id)
        identity = (
            db.scalar(select(SupplierIdentity).where(SupplierIdentity.id == run.identity_id))
            if run
            else None
        )
        website = identity.website if identity else None
        registry_hosts = registry_domains(identity.registry_ids if identity else None)
        rows = list(
            db.scalars(
                select(Source)
                .where(Source.run_id == run_id)
                .order_by(Source.fetched_at, Source.url)
            )
        )
        urls = {row.id: row.url for row in rows}
        sources = [
            SourceText(
                id=row.id,
                url=row.url,
                fetched_at=row.fetched_at,
                author=row.author,
                text=row.redacted_text,
                source_type=classify_source(
                    row.url,
                    website,
                    registry_hosts,
                    urls.get(row.linked_from_source_id) if row.linked_from_source_id else None,
                ),
                publisher=host_of(row.url) or row.url[:300],
                normalised=normalise(row.redacted_text),
            )
            for row in rows
        ]
        return sources, identity_redaction(db, run_id)


def _store(
    context: StageContext,
    section_id: str,
    items: list[FieldDefinition],
    kept: dict[str, Kept],
    tally: Tally,
) -> None:
    """One transaction for the section: its facts and its counts, or nothing."""
    with context.database.session() as db:
        run = db.scalar(select(ProfileRun).where(ProfileRun.id == context.run_id).with_for_update())
        if run is None:
            return
        stored = set(db.scalars(select(Fact.field).where(Fact.run_id == context.run_id)))
        if any(item.id in stored for item in items):
            return  # another execution stored this section first: counted there, not twice
        for item in items:
            fact = Fact(
                run_id=context.run_id,
                organisation_id=context.organisation_id,
                section=section_id,
                field=item.id,
                status="not_found",
            )
            result = kept.get(item.id)
            if result is not None:
                fact.status = "proposed"
                fact.value, fact.quote = result.value, result.quote
                fact.quote_redacted = result.quote_redacted
                fact.source_id, fact.source_url = result.source.id, result.source.url
                fact.source_type = result.source.source_type
                fact.publisher = result.source.publisher[:300]
                fact.author = result.source.author
                fact.fetched_at = result.source.fetched_at
            db.add(fact)
        run.grounding_failures += tally.grounding_failures
        run.invalid_items += tally.invalid_items
        db.commit()
    logger.info(
        "Extraction for run %s, section %s: %d of %d fields kept, %d grounding failures, "
        "%d invalid items",
        context.run_id,
        section_id,
        len(kept),
        len(items),
        tally.grounding_failures,
        tally.invalid_items,
    )
