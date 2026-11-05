"""The member's own inputs for a profile (spec Data model: BuyerInput; #26).

One row per run and field. The field is a `buyer` field of the profile definition, or one of the
reserved fields `fit_criteria` and `buyer_context`, whose `text` holds a structured value (JSON)
written by `app.buyer.values`. `version` starts at 1 and grows with every write: a write based on
an older version is refused (409), so that no edit is lost. The content is commercially sensitive
and belongs to the organisation only; it goes with the run when the profile or the organisation
is deleted.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.ownership import OrganisationOwned

FIT_CRITERIA = "fit_criteria"
BUYER_CONTEXT = "buyer_context"
RESERVED_FIELDS = (FIT_CRITERIA, BUYER_CONTEXT)


class BuyerInput(OrganisationOwned, Base):
    __tablename__ = "buyer_inputs"
    __table_args__ = (UniqueConstraint("run_id", "field", name="uq_buyer_inputs_run_field"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile_runs.id", ondelete="CASCADE"), index=True
    )
    field: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
