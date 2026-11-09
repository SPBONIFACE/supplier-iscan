"""The collection stage of a run (spec Flow 1 step 4, F2).

Since #103 the stage is `DEFAULT_STAGES["collection"]` (`app.runs.stages.collection_stage`).
GUARD (#19): `make_collection_stage` raises `RedactionNotWired` unless
`source_store.REDACTION_WIRED` is True, that is unless the single source-storage function
redacts. Tests pass `allow_unredacted=True` with synthetic fixture sites and mock transports.

Every outbound request of the run (permission checks included) passes a `RequestBudget` (#103).
"""

import logging
from collections.abc import Callable
from functools import partial

from sqlalchemy import delete, select

from app.collection import source_store
from app.collection.budget import RequestBudget
from app.collection.collector import Collector
from app.collection.failures import RetrievalFailed
from app.collection.gleif_source import store_gleif_source
from app.collection.retrieval import IdentityRecord, make_retriever
from app.collection.settings import CollectionSettings, load_collection_settings
from app.collection.source_store import SourceRecord, identity_redaction, store_source
from app.crawl import DatabaseSuppressionList, PermittedFetcher, build_client, record_permission
from app.http_client import GuardedClient
from app.limits.budget import RunBudgetExhausted
from app.models import ProfileRun, RunFailure, SupplierIdentity
from app.prompts import PromptSet, load_prompt_set
from app.redaction import gate_for
from app.registries.http import Fetch
from app.runs.stages import Stage, StageContext, StageOutcome

logger = logging.getLogger(__name__)


BUDGET_MESSAGE = "The run reached its cost budget, so the search for further sources was not made."


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
    client_factory: Callable[..., GuardedClient] | None = None,
    prompt_set: PromptSet | None = None,
    gleif_fetch: Fetch | None = None,
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
            lei = (identity.registry_ids or {}).get("lei")
            redaction = identity_redaction(db, context.run_id)
            # Owner decision (3 Nov 2026): a natural person's name and address are hidden from the
            # provider, so with no website to anchor it the query would identify nobody.
            skip_retrieval = identity.natural_person and not identity.website
        retriever: Callable[[list[str]], list[str]] | None = None
        budget_reached = False
        if skip_retrieval:
            logger.info(
                "Run %s: the search for further sources was skipped, because the supplier is a "
                "natural person without a website and the query would identify nobody.",
                context.run_id,
            )
        elif context.providers is not None:
            search = make_retriever(
                context.providers,
                prompt_set or load_prompt_set(),
                gate_for(database),
                redaction,
                record,
                context.call_context,
            )

            def budgeted(lacking: list[str]) -> list[str]:
                nonlocal budget_reached
                try:
                    return search(lacking)
                except RunBudgetExhausted:
                    # The call was not made (#30). The failure log says so, the collected
                    # sources are kept, and the run ends `partial` once they are stored.
                    budget_reached = True
                    raise RetrievalFailed("attempt_cap", BUDGET_MESSAGE) from None

            retriever = budgeted

        # The GLEIF source first (#142): stored before anything else, so the extraction reads it
        # first. GLEIF unavailable: the run goes on, and the failure log says so.
        def store_gleif(source: SourceRecord) -> None:
            store_source(database, context.run_id, context.organisation_id, source)

        gleif_failure = store_gleif_source(
            lei if isinstance(lei, str) else None, store_gleif, gleif_fetch
        )
        # Every outbound request of the run, permission checks included, passes this budget.
        budget = RequestBudget(limits.max_requests, limits.max_domains)
        client = (
            client_factory(before_request=budget)
            if client_factory
            else build_client(contact_url, before_request=budget)
        )
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
            failures = [gleif_failure, *result.failures] if gleif_failure else result.failures
            for position, failure in enumerate(failures):
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
        if budget_reached:
            # Not "insufficient sources": the search for further sources was not made, so
            # nothing is known about what exists (and the run counts against the quota).
            raise RunBudgetExhausted
        # Every strategy failed and nothing usable exists: not counted against the quota.
        return None if result.sources else "insufficient_sources"

    return stage
