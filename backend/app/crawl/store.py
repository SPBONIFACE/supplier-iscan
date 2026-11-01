"""Storage of crawl permissions and the suppression list, and the exclusions shown on a run."""

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawl.permissions import EXCLUSION_MESSAGE, DomainPermission
from app.db import Database, utc_now
from app.models import CrawlPermission, SuppressionEntry


def record_permission(
    database: Database, run_id: uuid.UUID, organisation_id: uuid.UUID, permission: DomainPermission
) -> None:
    """Store the permission of a domain for a run; a second check of the same domain replaces it."""
    with database.session() as db:
        row = db.scalar(
            select(CrawlPermission).where(
                CrawlPermission.run_id == run_id, CrawlPermission.domain == permission.domain
            )
        )
        if row is None:
            row = CrawlPermission(
                run_id=run_id, organisation_id=organisation_id, domain=permission.domain
            )
            db.add(row)
        row.robots_result = permission.robots_result
        row.tdm_reservation = permission.tdm_reservation
        row.suppression_hit = permission.suppression_hit
        row.decision = permission.decision
        row.checked_at = permission.checked_at or utc_now()
        db.commit()


def excluded_sources(
    db: Session, organisation_id: uuid.UUID, run_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, str]]]:
    """Per run, the domains excluded at the site owner's request, with the message to show.

    Nothing else of the `CrawlPermission` record leaves this function.
    """
    result: dict[uuid.UUID, list[dict[str, str]]] = {}
    rows = db.execute(
        select(CrawlPermission.run_id, CrawlPermission.domain)
        .where(
            CrawlPermission.organisation_id == organisation_id,
            CrawlPermission.run_id.in_(set(run_ids)),
            CrawlPermission.decision == "excluded",
        )
        .order_by(CrawlPermission.checked_at, CrawlPermission.domain)
    )
    for run_id, domain in rows:
        result.setdefault(run_id, []).append({"domain": domain, "message": EXCLUSION_MESSAGE})
    return result


class DatabaseSuppressionList:
    """The active `domain` entries of the suppression list; an entry covers its subdomains."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def is_suppressed(self, domain: str) -> bool:
        labels = domain.lower().rstrip(".").split(".")
        candidates = {".".join(labels[i:]) for i in range(len(labels))}
        with self._database.session() as db:
            return (
                db.scalar(
                    select(SuppressionEntry.id)
                    .where(
                        SuppressionEntry.kind == "domain",
                        SuppressionEntry.removed_at.is_(None),
                        SuppressionEntry.value.in_(candidates),
                    )
                    .limit(1)
                )
                is not None
            )
