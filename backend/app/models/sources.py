"""Collected sources (spec Data model; #18).

A `Source` is one page or PDF of a run: URL, fetch time, content type, the extracted text and the
author when the PDF names one. The text is written only by `app.collection.source_store`
(redacted there from #19). `delete_after` and the retention jobs are #45.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.ownership import OrganisationOwned


class Source(OrganisationOwned, Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("run_id", "url", name="run_url"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile_runs.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(2000))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_type: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(300))
