"""The stored values of the reserved buyer fields, and how they are shown to the model (#26).

`fit_criteria` is stored as a JSON list of strings, `buyer_context` as a JSON object. The text sent
to a model states only what was entered; it is data, put inside fences by the prompt renderer and
redacted by the gate before the request is built.
"""

import json
from datetime import date
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assessment.rules import BuyerContext
from app.models import BuyerInput
from app.models.buyer import BUYER_CONTEXT, FIT_CRITERIA

Relationship = Literal["incumbent", "new"]
Intent = Literal["dual_sourcing", "cost_reduction", "capacity_security", "risk_reduction"]

RELATIONSHIP_TEXT: Final = {"incumbent": "incumbent supplier", "new": "new supplier"}
INTENT_TEXT: Final = {
    "dual_sourcing": "dual sourcing",
    "cost_reduction": "cost reduction",
    "capacity_security": "capacity security",
    "risk_reduction": "risk reduction",
}


class StoredContext(BaseModel):
    """The structured value of `buyer_context` (without its version and audit fields)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relationship: Relationship
    current_share_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    contract_end_date: date | None = None
    strategic_intent: list[Intent] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("strategic_intent")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate intent")
        return value


def dump_criteria(criteria: list[str]) -> str:
    return json.dumps(criteria, ensure_ascii=False)


def load_criteria_text(text: str) -> list[str]:
    value = json.loads(text)
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def dump_context(context: StoredContext) -> str:
    return context.model_dump_json()


def load_context_text(text: str) -> StoredContext:
    return StoredContext.model_validate_json(text)


def criteria_prompt_text(criteria: list[str]) -> str | None:
    """The criteria as a list for the prompt; None when there are none."""
    cleaned = [" ".join(item.split()) for item in criteria if item.strip()]
    return "\n".join(f"- {item}" for item in cleaned) if cleaned else None


def context_prompt_text(context: StoredContext) -> str:
    """What the member entered, and nothing else."""
    lines = [f"Relationship with the supplier: {RELATIONSHIP_TEXT[context.relationship]}"]
    if context.current_share_pct is not None:
        lines.append(f"Current share of category spend: {context.current_share_pct:g}%")
    if context.contract_end_date is not None:
        lines.append(f"Contract end date: {context.contract_end_date.isoformat()}")
    if context.strategic_intent:
        lines.append(
            "Strategic intent: " + ", ".join(INTENT_TEXT[item] for item in context.strategic_intent)
        )
    if context.notes and context.notes.strip():
        lines.append("Notes: " + " ".join(context.notes.split()))
    return "\n".join(lines)


def stored(db: Session, run_id: Any, field: str) -> BuyerInput | None:
    return db.scalar(
        select(BuyerInput).where(BuyerInput.run_id == run_id, BuyerInput.field == field)
    )


def run_criteria(db: Session, run_id: Any) -> list[str]:
    row = stored(db, run_id, FIT_CRITERIA)
    return load_criteria_text(row.text) if row is not None else []


def run_buyer_context(db: Session, run_id: Any) -> BuyerContext | None:
    """The buyer context of the run as the assessment uses it, or None when none was entered."""
    row = stored(db, run_id, BUYER_CONTEXT)
    if row is None:
        return None
    entered = load_context_text(row.text)
    return BuyerContext(
        version=row.version,
        text=context_prompt_text(entered),
        relationship=entered.relationship,
    )
