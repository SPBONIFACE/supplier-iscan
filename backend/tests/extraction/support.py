"""Helpers for the extraction tests: sources, a scripted structuring provider, a stage context.

No network and no real key: the provider is a fake that reads what the request holds (the source
id, the requested fields, the source text) and answers as the test says.
"""

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.db import Database
from app.extraction.settings import ExtractionSettings
from app.extraction.stage import make_extraction_stage
from app.models import Fact, ProfileRun, Source, SupplierIdentity
from app.profile_definition import ProfileDefinition, load_profile_definition
from app.prompts import PromptSet, load_prompt_set
from app.providers import Providers, StructuringRequest
from app.providers.fake import FakeStructuringAdapter, fake_adapters
from app.runs.stages import Stage, StageContext
from tests.providers.support import SENTINEL_KEY, catalogue, config, make_meter

FETCHED = datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
SITE = "https://www.acme.example"
DEFINITION: ProfileDefinition = load_profile_definition()
PROMPTS: PromptSet = load_prompt_set()
FACT_FIELDS = [f.id for f in DEFINITION.fields() if f.kind == "fact"]


@dataclass(frozen=True)
class Asked:
    """What one call to the provider held, read back from the request."""

    source_id: str
    fields: list[str]
    text: str
    data: str


_BLOCK = r"<<<+ BEGIN {name}\n(.*?)\n<<<+ END {name}"


def read_request(request: StructuringRequest) -> Asked:
    data = request.data.text

    def block(name: str) -> str:
        match = re.search(_BLOCK.format(name=name), data, re.DOTALL)
        assert match, f"no {name} block in the request"
        return match.group(1)

    fields = re.findall(r"^- (\w+):", block("fields"), re.MULTILINE)
    return Asked(block("source_id"), fields, block("source_text"), data)


def item(
    field_id: str, value: str, quote: str, source_id: str, status: str = "found"
) -> dict[str, Any]:
    return {
        "field": field_id,
        "status": status,
        "value": value,
        "quote": quote,
        "source_id": source_id,
    }


def not_found(field_id: str) -> dict[str, Any]:
    return {"field": field_id, "status": "not_found"}


Responder = Callable[[Asked], "list[dict[str, Any]] | str | Exception"]


@dataclass
class Scripted(FakeStructuringAdapter):
    """A structuring fake that answers each request with `respond(asked)`: a list of items, the
    raw text of an answer, or an exception to raise."""

    respond: Responder = field(default=lambda asked: [])
    asked: list[Asked] = field(default_factory=list)

    def generate_json(
        self, request: StructuringRequest, schema_name: str, json_schema: dict[str, object]
    ) -> Any:
        from app.providers.interface import StructuringOutput

        self.calls.append(request)
        self.schemas.append(schema_name)
        asked = read_request(request)
        self.asked.append(asked)
        result = self.respond(asked)
        if isinstance(result, Exception):
            raise result
        text = result if isinstance(result, str) else json.dumps({"extractions": result})
        return StructuringOutput(text)


def scripted(respond: Responder) -> Scripted:
    return Scripted(outputs=[], respond=respond)


def providers_with(adapter: FakeStructuringAdapter) -> Providers:
    cat = catalogue(config("primary"))
    return Providers(
        cat,
        {"GEMINI_API_KEY": SENTINEL_KEY},
        fake_adapters(cat, structuring=adapter),
        meter=make_meter(None),
    )


def set_identity(engine: Engine, run_id: uuid.UUID, **values: Any) -> None:
    with Session(engine) as db:
        run = db.get(ProfileRun, run_id)
        assert run is not None
        db.execute(
            update(SupplierIdentity).where(SupplierIdentity.id == run.identity_id).values(**values)
        )
        db.commit()


def add_source(
    engine: Engine,
    organisation_id: uuid.UUID,
    run_id: uuid.UUID,
    url: str,
    text: str,
    *,
    content_type: str = "text/html",
    author: str | None = None,
    linked_from: uuid.UUID | None = None,
) -> uuid.UUID:
    with Session(engine) as db:
        source = Source(
            run_id=run_id,
            organisation_id=organisation_id,
            url=url,
            fetched_at=FETCHED,
            content_type=content_type,
            redacted_text=text,
            author=author,
            linked_from_source_id=linked_from,
        )
        db.add(source)
        db.commit()
        return source.id


def facts_of(engine: Engine, run_id: uuid.UUID) -> dict[str, Fact]:
    with Session(engine) as db:
        return {f.field: f for f in db.scalars(select(Fact).where(Fact.run_id == run_id))}


def run_row(engine: Engine, run_id: uuid.UUID) -> ProfileRun:
    with Session(engine) as db:
        return db.scalars(select(ProfileRun).where(ProfileRun.id == run_id)).one()


def context_for(
    engine: Engine,
    organisation_id: uuid.UUID,
    run_id: uuid.UUID,
    providers: Providers | None,
) -> StageContext:
    return StageContext(
        run_id, organisation_id, "extraction", Database(None, engine), providers, lambda: None
    )


def stage(max_input_chars: int = 20_000, groups_per_call: int = 1) -> Stage:
    """The stage; one call per section by default, which most tests are written for (#147)."""
    return make_extraction_stage(
        DEFINITION,
        PROMPTS,
        ExtractionSettings(max_input_chars=max_input_chars, groups_per_call=groups_per_call),
    )


def extract_with(
    engine: Engine, organisation_id: uuid.UUID, run_id: uuid.UUID, adapter: FakeStructuringAdapter
) -> None:
    """Run the extraction stage of the run once, over the fake provider."""
    stage()(context_for(engine, organisation_id, run_id, providers_with(adapter)))
