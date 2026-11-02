"""The identity chat of F1 (#16): one session per supplier name, ending in a SupplierIdentity.

The transcript holds the member's free text and is personal data in the sense of the spec: it is
kept for the redacted-source-text retention period and deleted by #45 (owner decision, 27 Oct 2026).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.ownership import OrganisationOwned


class IdentitySession(OrganisationOwned, Base):
    __tablename__ = "identity_sessions"
    __table_args__ = (
        CheckConstraint("profile_language IN ('en', 'fr')", name="profile_language"),
        CheckConstraint("ui_language IN ('en', 'fr')", name="ui_language"),
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(300))
    # The member's hints {website, country, sector}; they rank, they never exclude.
    hints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    profile_language: Mapped[str] = mapped_column(String(2))
    ui_language: Mapped[str] = mapped_column(String(2))
    # The chat turns, in order (the IdentityTurn objects of the contract).
    transcript: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # The ranked candidates of the last search: [{"candidate": {...}, "natural_person": bool, ...}].
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    current_candidate_id: Mapped[str | None] = mapped_column(String(200))
    # {"gleif": "ok" | "unreachable", "wikidata": ...} of the last search.
    registries: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    identity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("supplier_identities.id"))
    # The prompt set the session used (#55).
    prompt_set_hash: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
