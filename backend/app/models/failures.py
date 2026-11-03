"""The failure log of a run's collection stage (spec F2; #20). Written by `app.collection.stage`,
read by `GET /runs/{id}/failures`. The message is fixed text (`app.collection.failures`).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.ownership import OrganisationOwned


class RunFailure(OrganisationOwned, Base):
    __tablename__ = "run_failures"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile_runs.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)  # order within the run
    url: Mapped[str | None] = mapped_column(String(2000))
    strategy: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(30))
    next_strategy: Mapped[str | None] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
