"""The redaction gate: the one function feature code calls to turn text into `RedactedText`.

It adds the active `person_name` entries of the suppression list to every call, and the confirmed
name and registered address of a natural person when the caller passes them (`natural_person`).
A company's legal name is never forced: it goes in `keep`, so that NER does not eat it.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import select

from app.db import Database
from app.models import SuppressionEntry
from app.redaction.engine import RedactionContext, Redactor, get_redactor
from app.redaction.text import RedactedText, RedactionUnavailable

logger = logging.getLogger(__name__)


def database_suppressed_names(database: Database) -> Callable[[], Sequence[str]]:
    """A reader of the active `person_name` suppression entries (read at every call)."""

    def read() -> Sequence[str]:
        with database.session() as db:
            return list(
                db.scalars(
                    select(SuppressionEntry.value).where(
                        SuppressionEntry.kind == "person_name",
                        SuppressionEntry.removed_at.is_(None),
                    )
                )
            )

    return read


@dataclass
class RedactionGate:
    suppressed_names: Callable[[], Sequence[str]]
    redactor: Redactor | None = None

    def redact(
        self,
        text: str,
        *,
        person_names: Sequence[str] = (),
        addresses: Sequence[str] = (),
        company_names: Sequence[str] = (),
    ) -> RedactedText:
        """`person_names` and `addresses`: of a natural-person identity, always redacted.
        `company_names`: legal names of companies, which NER must leave alone."""
        try:
            forced = (*self.suppressed_names(), *person_names)
        except Exception as error:  # noqa: BLE001 - without the list, nothing may pass
            logger.error("Suppression names could not be read: %s", type(error).__name__)
            raise RedactionUnavailable from None
        context = RedactionContext(
            names=tuple(forced), addresses=tuple(addresses), keep=tuple(company_names)
        )
        return (self.redactor or get_redactor()).redact(text, context)


def gate_for(database: Database) -> RedactionGate:
    return RedactionGate(database_suppressed_names(database))
