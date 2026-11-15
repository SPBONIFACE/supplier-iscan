"""The single source-storage function: the only writer of `Source.redacted_text`.

Redaction (#19) happens in `redact_for_storage`, the one place text passes before it is written:
emails, phone numbers and people's names become `[…]`, the active `person_name` suppression entries
are always redacted, and for a natural-person identity so are its confirmed name. If redaction
cannot run, `RedactionUnavailable` propagates: nothing is written, and the run pauses.
"""

import logging
import time
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Database
from app.models import ProfileRun, Source, SupplierIdentity
from app.redaction import RedactionGate, gate_for

logger = logging.getLogger(__name__)

# Lifts the guard of `app.collection.stage.ensure_collection_allowed` (#18): storage redacts.
REDACTION_WIRED = True


@dataclass(frozen=True)
class SourceRecord:
    url: str
    fetched_at: datetime
    content_type: str
    text: str
    author: str | None = None
    # For a PDF: the address of the page of the run that linked to it (stored before it).
    linked_from_url: str | None = None


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


def _redact_record(
    gate: RedactionGate, context: IdentityRedaction, record: SourceRecord
) -> tuple[str, str | None]:
    """The redacted text and author of a record. No database session is held: redaction can take
    a minute on a long text (#52, deployment findings)."""
    started = time.monotonic()
    text = redact_for_storage(record.text, gate, context)
    logger.info(
        "Redacted a source of %d characters in %.1f s", len(record.text), time.monotonic() - started
    )
    author = redact_for_storage(record.author, gate, context)[:300] if record.author else None
    return text, author


def store_source(
    database: Database, run_id: uuid.UUID, organisation_id: uuid.UUID, record: SourceRecord
) -> uuid.UUID:
    """Store a source of the run; storing the same URL again replaces it (a resumed stage)."""
    gate = gate_for(database)
    with database.session() as db:
        context = identity_redaction(db, run_id)
    # Redacted before anything is written; a failure raises before the row is touched.
    text, author = _redact_record(gate, context, record)
    return _write_source(database, run_id, organisation_id, record, text, author)


def _write_source(
    database: Database,
    run_id: uuid.UUID,
    organisation_id: uuid.UUID,
    record: SourceRecord,
    text: str,
    author: str | None,
) -> uuid.UUID:
    with database.session() as db:
        row = db.scalar(select(Source).where(Source.run_id == run_id, Source.url == record.url))
        if row is None:
            row = Source(run_id=run_id, organisation_id=organisation_id, url=record.url)
            db.add(row)
        row.fetched_at = record.fetched_at
        row.content_type = record.content_type[:100]
        row.redacted_text = text
        row.author = author
        # The page that linked to a PDF, when that page was stored (a page with no text is not).
        row.linked_from_source_id = (
            db.scalar(
                select(Source.id).where(
                    Source.run_id == run_id, Source.url == record.linked_from_url
                )
            )
            if record.linked_from_url
            else None
        )
        db.commit()
        return row.id


class SourceStorage:
    """Stores the sources of one run, redacting up to `concurrency` of them at the same time (#196).

    With `concurrency` 1 (or less) `submit` is `store_source`: redact, then write, before it
    returns. With more, `submit` starts the redaction on a worker thread and returns, so the crawl
    goes on; the rows are written here, on the caller's thread, in the order of `submit`, once their
    redaction is done (`submit` waits for the oldest when `concurrency` are in flight; `finish`
    waits for all). A redaction failure surfaces at the write of its source, before any later
    source is written. Nothing is written for text that was not redacted."""

    def __init__(
        self,
        database: Database,
        run_id: uuid.UUID,
        organisation_id: uuid.UUID,
        concurrency: int = 1,
    ) -> None:
        self._database = database
        self._run_id = run_id
        self._organisation_id = organisation_id
        self._concurrency = max(1, concurrency)
        self._executor: ThreadPoolExecutor | None = None
        self._pending: deque[tuple[SourceRecord, Future[tuple[str, str | None]]]] = deque()
        self._gate = gate_for(database)
        self._context: IdentityRedaction | None = None

    def submit(self, record: SourceRecord) -> None:
        if self._concurrency == 1:
            store_source(self._database, self._run_id, self._organisation_id, record)
            return
        if self._context is None:
            with self._database.session() as db:
                self._context = identity_redaction(db, self._run_id)
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._concurrency, thread_name_prefix="source-redaction"
            )
        while len(self._pending) >= self._concurrency:
            self._write_oldest()
        self._pending.append(
            (record, self._executor.submit(_redact_record, self._gate, self._context, record))
        )
        while self._pending and self._pending[0][1].done():
            self._write_oldest()

    def _write_oldest(self) -> None:
        record, future = self._pending.popleft()
        text, author = future.result()
        _write_source(self._database, self._run_id, self._organisation_id, record, text, author)

    def finish(self) -> None:
        """Write what is still being redacted, in order."""
        try:
            while self._pending:
                self._write_oldest()
        except BaseException:
            self.abandon()
            raise
        self._shutdown()

    def abandon(self) -> None:
        """Stop without writing the sources still pending (the run is stopping or failing)."""
        for _record, future in self._pending:
            future.cancel()
        self._pending.clear()
        self._shutdown()

    def _shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
