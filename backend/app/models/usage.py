"""Usage log (spec F7: every run, login and failed login is recorded)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Later issues add their kinds with a migration that widens the constraint.
USAGE_EVENT_KINDS = ("login", "login_failed", "run")


class UsageEvent(Base):
    """One entry of the usage log. Never holds a password, a hash or a session token.

    A failed login with an unknown email has neither user nor organisation.
    """

    __tablename__ = "usage_events"
    __table_args__ = (
        CheckConstraint(
            "kind IN (" + ", ".join(repr(kind) for kind in USAGE_EVENT_KINDS) + ")", name="kind"
        ),
        Index("ix_usage_events_organisation_id_created_at", "organisation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organisations.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
