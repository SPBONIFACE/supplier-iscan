"""Supplier identities, profile runs and the job queue (spec Data model; #13).

`SupplierIdentity` is created and confirmed by #16; #13 only reads it. `ProfileRun` is the record
the member follows. `Job` is the generic PostgreSQL job queue (`app.queue`): one row per unit of
work, claimed with `FOR UPDATE SKIP LOCKED` and held under a lease that expires.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.ownership import OrganisationOwned

RUN_STATUSES = (
    "queued",
    "running",
    "paused",
    "stopped",
    "failed",
    "insufficient_sources",
    "partial",
    "completed",
)
# A run in one of these states never changes again.
FINISHED_STATUSES = ("stopped", "failed", "insufficient_sources", "partial", "completed")
RUN_STAGES = ("identity", "collection", "extraction", "assessment")
RUN_DEPENDENCIES = (
    "structuring_provider",
    "retrieval_provider",
    "llm_provider",
    "registry",
    "website",
    "database",
    "network",
)
JOB_STATES = ("queued", "running", "done", "failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(repr(value) for value in values) + ")"


class SupplierIdentity(OrganisationOwned, Base):
    __tablename__ = "supplier_identities"

    legal_name: Mapped[str] = mapped_column(String(300))
    website: Mapped[str | None] = mapped_column(String(2000))
    country: Mapped[str | None] = mapped_column(String(100))
    sector: Mapped[str | None] = mapped_column(String(200))
    registry_ids: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    natural_person: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    # An identity is confirmed once it has a confirmation time (#16 sets both fields).
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProfileRun(OrganisationOwned, Base):
    __tablename__ = "profile_runs"
    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUSES), name="status"),
        CheckConstraint(_in("stage", RUN_STAGES), name="stage"),
        CheckConstraint(
            "pause_dependency IS NULL OR " + _in("pause_dependency", RUN_DEPENDENCIES),
            name="pause_dependency",
        ),
        Index("ix_profile_runs_organisation_id_created_at", "organisation_id", "created_at"),
    )

    identity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier_identities.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    # The stage being executed (or to execute next); earlier stages are complete.
    stage: Mapped[str] = mapped_column(String(20), default="identity")
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    counts_against_quota: Mapped[bool] = mapped_column(Boolean, default=True)
    pause_dependency: Mapped[str | None] = mapped_column(String(30))
    pause_reason: Mapped[str | None] = mapped_column(String(300))
    error: Mapped[str | None] = mapped_column(String(300))
    # Set by the stages that load the profile definition and the prompt set (#21, #26).
    profile_definition_hash: Mapped[str | None] = mapped_column(String(100))
    prompt_set_hash: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Base):
    """One unit of background work. Not organisation-owned: the payload only names ids."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_in("state", JOB_STATES), name="state"),
        Index("ix_jobs_state_lease_expires_at", "state", "lease_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(10), default="queued")
    locked_by: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
