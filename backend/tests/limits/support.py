"""Helpers for the run-budget tests (#30): providers that meter into the database and check the
budget, a structuring fake that bills every call, and the number of calls a budget allows.

With the test prices (USD 1.00 per million input tokens, 4.00 per million output tokens, 0.9 EUR
per USD), a call that reports 300 000 input tokens is billed 0.27 EUR, and the largest estimate of
a structuring attempt is a little above 0.0295 EUR (8192 output tokens) plus 0.0000009 EUR per
character of input. So `allow(n)` is a budget that lets exactly `n` billed calls through: the
next one would pass 0.03 above the total once its estimate (above 0.03 for any real prompt) is
added.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.db import Database
from app.limits.budget import RunBudget
from app.models import LlmUsage
from app.providers import Providers
from app.providers.fake import FakeRetrievalAdapter, FakeStructuringAdapter, fake_adapters
from app.providers.interface import StructuringOutput, StructuringRequest
from app.providers.metering import CallContext, CallUsage, UsageMeter
from app.providers.store import sync_provider_configs
from app.providers.usage import DbUsageSink
from tests.extraction.support import Scripted
from tests.providers.support import EUR_PER_USD, PRICES, SENTINEL_KEY, catalogue, config

CALL_COST = Decimal("0.27")
BILLED = CallUsage(input_tokens=300_000)  # CALL_COST with the test prices


def allow(calls: int) -> Decimal:
    return CALL_COST * calls + Decimal("0.03")


def providers_for(
    engine: Engine,
    structuring: FakeStructuringAdapter | None = None,
    retrieval: FakeRetrievalAdapter | None = None,
    budget: Decimal | None = None,
    max_retries: int = 1,
) -> Providers:
    """Providers that meter into `llm_usage` and check the run budget (none when `budget` is
    None) before every attempt."""
    database = Database(None, engine)
    cat = catalogue(config("primary"))
    with Session(engine) as db:
        sync_provider_configs(db, cat)
        db.commit()
    return Providers(
        cat,
        {"GEMINI_API_KEY": SENTINEL_KEY},
        fake_adapters(cat, structuring=structuring, retrieval=retrieval),
        meter=UsageMeter(PRICES, EUR_PER_USD, DbUsageSink(database)),
        budget=RunBudget(database, budget, max_retries) if budget is not None else None,
    )


@dataclass
class Billed(Scripted):
    """A scripted structuring fake whose every successful call reports `BILLED` usage."""

    def generate_json(
        self, request: StructuringRequest, schema_name: str, json_schema: dict[str, object]
    ) -> Any:
        output = super().generate_json(request, schema_name, json_schema)
        return StructuringOutput(output.text, BILLED)


@dataclass
class BilledText(FakeStructuringAdapter):
    """A structuring fake with scripted answer texts, every one billed `BILLED`."""

    def generate_json(
        self, request: StructuringRequest, schema_name: str, json_schema: dict[str, object]
    ) -> Any:
        output = super().generate_json(request, schema_name, json_schema)
        if isinstance(output, StructuringOutput):
            return StructuringOutput(output.text, BILLED)
        return output


def context_of(organisation_id: uuid.UUID, run_id: uuid.UUID) -> CallContext:
    return CallContext(organisation_id=organisation_id, run_id=run_id)


def usage_rows(engine: Engine, run_id: uuid.UUID) -> list[LlmUsage]:
    with Session(engine) as db:
        return list(
            db.scalars(
                select(LlmUsage).where(LlmUsage.run_id == run_id).order_by(LlmUsage.created_at)
            )
        )


def total_cost(engine: Engine, run_id: uuid.UUID) -> Decimal:
    with Session(engine) as db:
        total = db.scalar(
            select(func.coalesce(func.sum(LlmUsage.cost), 0)).where(LlmUsage.run_id == run_id)
        )
    return Decimal(total or 0)
