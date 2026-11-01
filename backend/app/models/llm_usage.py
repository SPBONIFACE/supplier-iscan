"""Per-call LLM usage (spec Data model: LlmUsage; #12).

One row per provider call attempt, written by `app.providers.metering`. Run totals, the monthly
spend (#29) and the run budget (#30) are computed from these rows. A row never holds the prompt or
the response text. `output_tokens` excludes `reasoning_tokens`. `run_id` has no foreign key yet:
the run table arrives with #13, which adds it.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

LLM_ROLES = ("retrieval", "structuring")
LLM_OUTCOMES = ("success", "invalid_output", "failed")
LLM_COST_BASES = ("provider", "price_table", "unreported")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(repr(value) for value in values) + ")"


class LlmUsage(Base):
    __tablename__ = "llm_usage"
    __table_args__ = (
        CheckConstraint(_in("role", LLM_ROLES), name="role"),
        CheckConstraint(_in("outcome", LLM_OUTCOMES), name="outcome"),
        CheckConstraint(_in("cost_basis", LLM_COST_BASES), name="cost_basis"),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND reasoning_tokens >= 0"
            " AND tool_calls >= 0 AND attempt >= 1 AND cost >= 0 AND billed_amount >= 0",
            name="non_negative",
        ),
        Index("ix_llm_usage_run_id", "run_id"),
        Index("ix_llm_usage_organisation_id_created_at", "organisation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    run_id: Mapped[uuid.UUID | None] = mapped_column()
    provider_config_id: Mapped[str] = mapped_column(ForeignKey("provider_configs.id"))
    provider: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int] = mapped_column()
    output_tokens: Mapped[int] = mapped_column()
    reasoning_tokens: Mapped[int] = mapped_column()
    tool_calls: Mapped[int] = mapped_column()
    attempt: Mapped[int] = mapped_column()
    outcome: Mapped[str] = mapped_column(String(20))
    # What the provider billed, in its currency; the EUR cost is billed_amount x exchange_rate.
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    billed_currency: Mapped[str] = mapped_column(String(3))
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    cost: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    cost_basis: Mapped[str] = mapped_column(String(20))
    price_as_of: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
