"""The single source-storage function: the only writer of `Source.redacted_text`.

Redaction (#19) happens in `redact_for_storage`, the one place text passes before it is written:
emails, phone numbers and people's names become `[…]`, the active `person_name` suppression entries
are always redacted, and for a natural-person identity so are its confirmed name. If redaction
cannot run, `RedactionUnavailable` propagates: nothing is written, and the run pauses.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Database
from app.models import ProfileRun, Source, SupplierIdentity
from app.redaction import RedactionGate, gate_for

# Lifts the guard of `app.collection.stage.ensure_collection_allowed` (#18): storage redacts.
REDACTION_WIRED = True


@dataclass(frozen=True)
class SourceRecord:
    url: str
    fetched_at: datetime
    content_type: str
    text: str
    author: str | None = None


@dataclass(frozen=True)
class IdentityRedaction:
    """What the run's identity adds to redaction: a natural person's name is always redacted,
    a company's legal name is protected from NER."""

    person_names: tuple[str, ...] = ()
    addresses: tuple[str, ...] = ()
    company_names: tuple[str, ...] = ()


def redact_for_storage(text: str, gate: RedactionGate, context: IdentityRedaction) -> str:
    """The text as it may be written: only `RedactedText` ever reaches `Source.redacted_text`."""
    redacted = gate.redact(
        text,
        person_names=context.person_names,
        addresses=context.addresses,
        company_names=context.company_names,
    )
    return redacted.text


def identity_redaction(db: Session, run_id: uuid.UUID) -> IdentityRedaction:
    identity = db.scalar(
        select(SupplierIdentity)
        .join(ProfileRun, ProfileRun.identity_id == SupplierIdentity.id)
        .where(ProfileRun.id == run_id)
    )
    if identity is None:
        return IdentityRedaction()
    if identity.natural_person:
        addresses = (identity.registered_address,) if identity.registered_address else ()
        return IdentityRedaction(person_names=(identity.legal_name,), addresses=addresses)
    return IdentityRedaction(company_names=(identity.legal_name,))


def store_source(
    database: Database, run_id: uuid.UUID, organisation_id: uuid.UUID, record: SourceRecord
) -> uuid.UUID:
    """Store a source of the run; storing the same URL again replaces it (a resumed stage)."""
    gate = gate_for(database)
    with database.session() as db:
        context = identity_redaction(db, run_id)
        # Redacted before anything is written; a failure raises before the row is touched.
        text = redact_for_storage(record.text, gate, context)
        author = redact_for_storage(record.author, gate, context)[:300] if record.author else None
        row = db.scalar(select(Source).where(Source.run_id == run_id, Source.url == record.url))
        if row is None:
            row = Source(run_id=run_id, organisation_id=organisation_id, url=record.url)
            db.add(row)
        row.fetched_at = record.fetched_at
        row.content_type = record.content_type[:100]
        row.redacted_text = text
        row.author = author
        db.commit()
        return row.id
