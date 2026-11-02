"""Crawl permissions and the suppression list (spec Data model; #17).

`CrawlPermission` is written by the worker, one row per run and domain, and read by the
administrator only: members see the exclusion message of their run, never the record.
`SuppressionEntry` is only a table here: adding and removing entries is administration (#46).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.ownership import OrganisationOwned

ROBOTS_RESULTS = ("not_checked", "found", "missing", "ai_blocked", "blocked", "unreachable")
CRAWL_DECISIONS = ("allowed", "excluded", "not_crawled", "blocked")
SUPPRESSION_KINDS = ("domain", "person_name")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(repr(value) for value in values) + ")"


class CrawlPermission(OrganisationOwned, Base):
    __tablename__ = "crawl_permissions"
    __table_args__ = (
        CheckConstraint(_in("robots_result", ROBOTS_RESULTS), name="robots_result"),
        CheckConstraint(_in("decision", CRAWL_DECISIONS), name="decision"),
        UniqueConstraint("run_id", "domain", name="run_domain"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile_runs.id", ondelete="CASCADE"), index=True
    )
    domain: Mapped[str] = mapped_column(String(300))
    robots_result: Mapped[str] = mapped_column(String(20))
    tdm_reservation: Mapped[bool] = mapped_column(Boolean, default=False)
    suppression_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    decision: Mapped[str] = mapped_column(String(20))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SuppressionEntry(Base):
    """Not organisation-owned: the list is the operator's, and applies to every run."""

    __tablename__ = "suppression_entries"
    __table_args__ = (
        CheckConstraint(_in("kind", SUPPRESSION_KINDS), name="kind"),
        Index("ix_suppression_entries_kind_value", "kind", "value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(20))
    # A domain in lower case, or a person's name (personal data: the table is administrator-only).
    value: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str | None] = mapped_column(String(500))
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    added_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    removal_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
