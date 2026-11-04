"""The facts of a run (spec Data model; F3, #23).

One `Fact` per run and field: the value kept by extraction with its verbatim quote and
attribution, or `not_found` ("No public evidence found") when no value was kept. The quote can
identify a person despite redaction, so it is treated as personal data (retention: #45). Review
(`approved`, `corrected`) is #28.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.ownership import OrganisationOwned

FACT_STATUSES = ("proposed", "approved", "corrected", "not_found")
SOURCE_TYPES = ("supplier_claim", "third_party")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(repr(value) for value in values) + ")"


class Fact(OrganisationOwned, Base):
    __tablename__ = "facts"
    __table_args__ = (
        UniqueConstraint("run_id", "field", name="run_field"),
        CheckConstraint(_in("status", FACT_STATUSES), name="status"),
        CheckConstraint(
            "source_type IS NULL OR " + _in("source_type", SOURCE_TYPES), name="source_type"
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile_runs.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[str] = mapped_column(String(200))
    field: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    value: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text)
    quote_redacted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # The source can be deleted by retention (#45); the attribution below stays with the fact.
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL")
    )
    source_url: Mapped[str | None] = mapped_column(String(2000))
    source_type: Mapped[str | None] = mapped_column(String(20))
    publisher: Mapped[str | None] = mapped_column(String(300))
    author: Mapped[str | None] = mapped_column(String(300))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
