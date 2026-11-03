"""The collection stage of a run (spec Flow 1 step 4, F2).

GUARD (#19): the stage is not in `DEFAULT_STAGES`, and `make_collection_stage` raises
`RedactionNotWired` until `source_store.REDACTION_WIRED` is True, that is until #19 makes the
single source-storage function redact. Personal data on a real site would otherwise be stored
unredacted. Tests pass `allow_unredacted=True` with synthetic fixture sites and mock transports.
"""

import logging
from collections.abc import Callable
from functools import partial

from sqlalchemy import delete, select

from app.collection import source_store
from app.collection.collector import Collector
from app.collection.retrieval import IdentityRecord, make_retriever
from app.collection.settings import CollectionSettings, load_collection_settings
from app.collection.source_store import SourceRecord, identity_redaction, store_source
from app.crawl import DatabaseSuppressionList, PermittedFetcher, build_client, record_permission
from app.http_client import GuardedClient
from app.models import ProfileRun, RunFailure, SupplierIdentity
from app.prompts import PromptSet, load_prompt_set
from app.redaction import gate_for
from app.runs.stages import Stage, StageContext, StageOutcome

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
    prompt_set: PromptSet | None = None,
) -> Stage:
    """The `collection` stage. `client_factory` is for tests (a client over a mock transport).

    The ladder is the website, its sitemaps, then the retrieval provider (when the run has
    providers). The stage ends the run `insufficient_sources` when no source was collected.
    """
    ensure_collection_allowed(allow_unredacted)
    limits = settings or load_collection_settings()

    def stage(context: StageContext) -> StageOutcome | None:
        database = context.database
        with database.session() as db:
            run = db.get(ProfileRun, context.run_id)
            identity = (
                db.scalar(select(SupplierIdentity).where(SupplierIdentity.id == run.identity_id))
                if run
                else None
            )
            if identity is None:
                return None
            record = IdentityRecord(identity.legal_name, identity.website, identity.country)
            redaction = identity_redaction(db, context.run_id)
        retriever = None
        if context.providers is not None:
            retriever = make_retriever(
                context.providers,
                prompt_set or load_prompt_set(),
                gate_for(database),
                redaction,
                record,
                context.call_context,
            )
        client = client_factory() if client_factory else build_client(contact_url)
        with client:
            fetcher = PermittedFetcher(
                client,
                DatabaseSuppressionList(database),
                partial(record_permission, database, context.run_id, context.organisation_id),
            )

            def store(source: SourceRecord) -> None:
                store_source(database, context.run_id, context.organisation_id, source)

            collector = Collector(fetcher, limits, store, check_stop=context.check_stop)
            result = collector.collect(record.website, record.legal_name, retriever)
        with database.session() as db:
            run = db.get(ProfileRun, context.run_id)
            if run is not None:
                run.identity_to_verify = result.identity_to_verify
            # A stage executed again replaces its log instead of doubling it.
            db.execute(delete(RunFailure).where(RunFailure.run_id == context.run_id))
            for position, failure in enumerate(result.failures):
                db.add(
                    RunFailure(
                        organisation_id=context.organisation_id,
                        run_id=context.run_id,
                        position=position,
                        url=failure.url[:2000] if failure.url else None,
                        strategy=failure.strategy,
                        kind=failure.kind,
                        next_strategy=failure.next_strategy,
                        message=failure.message,
                    )
                )
            db.commit()
        logger.info(
            "Collected %d sources for run %s (%d skipped, %d attempts)",
            len(result.sources),
            context.run_id,
            len(result.skipped),
            result.attempts,
        )
        # Every strategy failed and nothing usable exists: not counted against the quota.
        return None if result.sources else "insufficient_sources"

    return stage
