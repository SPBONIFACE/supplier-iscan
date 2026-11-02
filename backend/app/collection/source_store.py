"""The single source-storage function: the only writer of `Source.text`.

Redaction (#19) goes in `redact_for_storage`, the one place text passes before it is written.
Until #19 is merged it returns the text unchanged, and `REDACTION_WIRED` is False: the collection
stage refuses to run against real sites (`app.collection.stage.ensure_collection_allowed`).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.db import Database
from app.models import Source

# TODO(#19): set to True when `redact_for_storage` redacts personal data.
REDACTION_WIRED = False


@dataclass(frozen=True)
class SourceRecord:
    url: str
    fetched_at: datetime
    content_type: str
    text: str
    author: str | None = None


def redact_for_storage(text: str) -> str:
    """The text as it may be written. #19 replaces the body with the redaction pipeline."""
    return text


def store_source(
    database: Database, run_id: uuid.UUID, organisation_id: uuid.UUID, record: SourceRecord
) -> uuid.UUID:
    """Store a source of the run; storing the same URL again replaces it (a resumed stage)."""
    with database.session() as db:
        row = db.scalar(select(Source).where(Source.run_id == run_id, Source.url == record.url))
        if row is None:
            row = Source(run_id=run_id, organisation_id=organisation_id, url=record.url)
            db.add(row)
        row.fetched_at = record.fetched_at
        row.content_type = record.content_type[:100]
        row.text = redact_for_storage(record.text)
        row.author = redact_for_storage(record.author)[:300] if record.author else None
        db.commit()
        return row.id
