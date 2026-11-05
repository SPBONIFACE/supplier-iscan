"""The assessment statements of a run (spec Data model: AssessmentStatement; F8, #25).

One row per kept statement, with the facts it cites and its provenance: provider, model ID, the
approved configuration that pins the model version, the prompt id and version, the generation
time, and the review status (`ai_draft` until #28 reviews it). There is no score column.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.ownership import OrganisationOwned

STATEMENT_KINDS = (
    "strength",
    "weakness",
    "opportunity",
    "threat",
    "risk_indicator",
    "evidence_gap",
    "fit",
    "procurement_implication",
    "relationship_level",
    "contract_approach",
    "volume_share",
    "next_action",
    "procurement_priority",
)
STATEMENT_STATUSES = ("ai_draft", "approved", "corrected", "deleted")
LEVELS = ("low", "medium", "high")
LABELS = ("strategic", "preferred", "transactional")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(repr(value) for value in values) + ")"


class AssessmentItem(OrganisationOwned, Base):
    __tablename__ = "assessment_statements"
    __table_args__ = (
        CheckConstraint(_in("kind", STATEMENT_KINDS), name="kind"),
        CheckConstraint(_in("status", STATEMENT_STATUSES), name="status"),
        CheckConstraint("level IS NULL OR " + _in("level", LEVELS), name="level"),
        CheckConstraint("label IS NULL OR " + _in("label", LABELS), name="label"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile_runs.id", ondelete="CASCADE"), index=True
    )
    # The order of the draft, so that the answer is stable.
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    level: Mapped[str | None] = mapped_column(String(10))
    label: Mapped[str | None] = mapped_column(String(20))
    timing: Mapped[str | None] = mapped_column(String(200))
    # Ids of facts of the run (no foreign key: a fact is replaced by review, #28).
    cited_fact_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    cites_buyer_context: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    gap_evidence: Mapped[str | None] = mapped_column(Text)
    buyer_context_version: Mapped[int | None] = mapped_column(Integer)
    # The financial guidance (#26) of a statement written by rules in code; null for the others.
    guidance: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # Provenance.
    provider: Mapped[str] = mapped_column(String(50))
    model_id: Mapped[str] = mapped_column(String(200))
    model_version: Mapped[str] = mapped_column(String(100))
    prompt_id: Mapped[str] = mapped_column(String(50))
    prompt_version: Mapped[str] = mapped_column(String(100))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="ai_draft")
