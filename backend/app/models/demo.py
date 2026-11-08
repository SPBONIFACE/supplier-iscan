"""The public demo's profiles (spec Data model: DemoProfile; #50).

A read-only copy of a finished run of the configured demo organisation, with person names
stripped. It belongs to no organisation (no `organisation_id`, no foreign key to a run, a user or a
source): the demo routes read this table and nothing else, so the demo cannot reach any
organisation's data. Only the administrator command `python -m app.demo` writes it.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DemoProfile(Base):
    __tablename__ = "demo_profiles"

    # A new id, not the run's: the id of a real run never opens a demo route.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The order of the demo list.
    position: Mapped[int] = mapped_column(Integer)
    # Always true: the flag of the spec's "flagged `demo`".
    demo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    supplier_name: Mapped[str] = mapped_column(String(300))
    # The header and flags of the profile (a `DemoRun` without its id).
    run: Mapped[dict[str, Any]] = mapped_column(JSON)
    # The facts (`Fact`), the assessment (`Assessment`) and the sources' metadata, as stored.
    facts: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    assessment: Mapped[dict[str, Any]] = mapped_column(JSON)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
