"""The collection stage of a run (spec Flow 1 step 4, F2).

GUARD (#19): the stage is not in `DEFAULT_STAGES`, and `make_collection_stage` raises
`RedactionNotWired` until `source_store.REDACTION_WIRED` is True, that is until #19 makes the
single source-storage function redact. Personal data on a real site would otherwise be stored
unredacted. Tests pass `allow_unredacted=True` with synthetic fixture sites and mock transports.
"""

import logging
from collections.abc import Callable
from functools import partial

from sqlalchemy import select

from app.collection import source_store
from app.collection.collector import Collector
from app.collection.settings import CollectionSettings, load_collection_settings
from app.collection.source_store import SourceRecord, store_source
from app.crawl import DatabaseSuppressionList, PermittedFetcher, build_client, record_permission
from app.http_client import GuardedClient
from app.models import ProfileRun, SupplierIdentity
from app.runs.stages import Stage, StageContext

logger = logging.getLogger(__name__)


class RedactionNotWired(RuntimeError):
    """Collection was asked to run before #19 made source storage redact."""


def ensure_collection_allowed(allow_unredacted: bool = False) -> None:
    if not source_store.REDACTION_WIRED and not allow_unredacted:
        raise RedactionNotWired(
            "Collection is disabled until redaction before storage (#19) is merged."
        )


def make_collection_stage(
    contact_url: str | None,
    settings: CollectionSettings | None = None,
    *,
    allow_unredacted: bool = False,
    client_factory: Callable[[], GuardedClient] | None = None,
) -> Stage:
    """The `collection` stage. `client_factory` is for tests (a client over a mock transport)."""
    ensure_collection_allowed(allow_unredacted)
    limits = settings or load_collection_settings()

    def stage(context: StageContext) -> None:
        database = context.database
        with database.session() as db:
            run = db.get(ProfileRun, context.run_id)
            identity = (
                db.scalar(select(SupplierIdentity).where(SupplierIdentity.id == run.identity_id))
                if run
                else None
            )
            if identity is None or not identity.website:
                return None
            website, legal_name = identity.website, identity.legal_name
        client = client_factory() if client_factory else build_client(contact_url)
        with client:
            fetcher = PermittedFetcher(
                client,
                DatabaseSuppressionList(database),
                partial(record_permission, database, context.run_id, context.organisation_id),
            )

            def store(record: SourceRecord) -> None:
                store_source(database, context.run_id, context.organisation_id, record)

            collector = Collector(fetcher, limits, store, check_stop=context.check_stop)
            result = collector.collect(website, legal_name)
        with database.session() as db:
            run = db.get(ProfileRun, context.run_id)
            if run is not None:
                run.identity_to_verify = result.identity_to_verify
                db.commit()
        logger.info(
            "Collected %d sources for run %s (%d skipped)",
            len(result.sources),
            context.run_id,
            len(result.skipped),
        )
        return None

    return stage
