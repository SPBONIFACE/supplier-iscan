"""The retrieval step of collection (spec F2, Integrations, LLM features: Retrieval).

The retrieval provider gets the identity record (legal name, website, country) and the field
groups still lacking evidence, as text that passed the redaction gate (#19; for a natural person
the name and address are redacted). It returns addresses. Only the addresses leave this module:
the collector fetches each one through `PermittedFetcher` and stores it like a crawled source. The
answer text and the snippets are never stored and never become a fact; a snippet only ranks.
A provider outage or an unusable answer raises `RetrievalFailed` (logged, the run continues);
`RedactionUnavailable` is not caught: it fails closed and the run pauses.
"""

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from pydantic import ValidationError

from app.collection.collector import RetrievedAddresses, RetrieveFn
from app.collection.failures import RetrievalFailed
from app.collection.pages import classify
from app.collection.source_store import IdentityRedaction
from app.countries import country_name
from app.limits.budget import RunBudgetExhausted
from app.prompts import PromptSet
from app.providers import (
    ProviderCallError,
    ProviderError,
    Providers,
    RetrievalClient,
    RetrievalRequest,
    RetrievedUrl,
    StructuredOutputInvalid,
)
from app.providers.failures import validation_detail
from app.providers.metering import CallContext
from app.redaction import RedactionGate
from app.runs.stages import RunStopped

logger = logging.getLogger(__name__)

PROMPT_ID = "retrieval"

# Waits before the first and the second retry of a rate-limited request (`Retry-After` is not
# exposed by the provider errors).
RATE_LIMIT_WAITS = (2.0, 4.0)


# Asked when the website gave every page kind: sources other than the supplier's own pages.
INDEPENDENT_REQUEST = (
    "No field group lacks evidence on the supplier's own website. Return independent sources "
    "only: official registers, certification bodies, news and trade press. Not further pages "
    "of the supplier's own website."
)


# One line per focus, sent to the provider inside the supplier data text.
FOCUS_LINES = {
    "registers": (
        "Focus: official registers and filed accounts (company, lobby or transparency "
        "registers, filed annual accounts or annual report)"
    ),
    "certifications": "Focus: certification bodies' listings of certified companies",
    "news": (
        "Focus: news and trade press of the last two years (investments, plants, acquisitions, "
        "customers)"
    ),
    "customers": "Focus: pages naming the supplier's customers or brand partners",
}


@dataclass(frozen=True)
class IdentityRecord:
    legal_name: str
    website: str | None
    country: str | None


def _supplier_text(identity: IdentityRecord, lacking: list[str], focus: str | None = None) -> str:
    lines = [f"Legal name: {identity.legal_name}"]
    if identity.website:
        lines.append(f"Website: {identity.website}")
    if identity.country:
        name = country_name(identity.country)
        lines.append(
            f"Country: {name} ({identity.country})"
            if name != identity.country
            else f"Country: {name}"
        )
    if lacking:
        lines.append("Field groups lacking evidence: " + ", ".join(lacking))
    else:
        lines.append(INDEPENDENT_REQUEST)
    if focus in FOCUS_LINES:
        lines.append(FOCUS_LINES[focus])
    return "\n".join(lines)


def rank(urls: list[RetrievedUrl], lacking: list[str]) -> list[str]:
    """The addresses, those whose address or snippet points at a lacking group first. The snippet
    is used here only and is dropped."""
    wanted = set(lacking)
    scored = [(0 if classify(item.url, item.snippet) in wanted else 1, item.url) for item in urls]
    return [url for _score, url in sorted(scored, key=lambda pair: pair[0])]


def _round_robin(lists: list[list[str]]) -> list[str]:
    """The first address of each list, then the second of each, ...; a repeat is dropped."""
    merged: list[str] = []
    for position in range(max((len(items) for items in lists), default=0)):
        for items in lists:
            if position < len(items) and items[position] not in merged:
                merged.append(items[position])
    return merged


def make_retriever(
    providers: Providers,
    prompts: PromptSet,
    gate: RedactionGate,
    redaction: IdentityRedaction,
    identity: IdentityRecord,
    context: CallContext,
    focuses: tuple[str, ...] = (),
    *,
    concurrency: int = 2,
    wait: Callable[[float], None] = time.sleep,
    check_stop: Callable[[], None] = lambda: None,
) -> RetrieveFn:
    """One request per focus (none: a single request without focus), at most `concurrency` at the
    same time. A request refused as rate-limited is retried twice, after 2 s then 4 s (`wait`);
    `check_stop` is called after each wait. A focus whose request fails is reported in `failures`
    of the result (each with its own kind) and the others still run."""

    def prepare(lacking: list[str], focus: str | None) -> RetrievalRequest:
        """On the caller's thread: the redaction gate may read the database."""
        text = _supplier_text(identity, lacking, focus)
        rendered = prompts.render(PROMPT_ID, {"supplier": text})
        # Redacted before the call; a failure raises RedactionUnavailable and nothing is sent.
        query = gate.redact(
            rendered.data,
            person_names=redaction.person_names,
            addresses=redaction.addresses,
            company_names=redaction.company_names,
        )
        return RetrievalRequest(rendered.instructions, query)

    def send(client: RetrievalClient, request: RetrievalRequest, lacking: list[str]) -> list[str]:
        """The provider call alone (it runs in a pool thread): no database session of the stage."""
        retries = 0
        while True:
            try:
                result = client.retrieve(request, context)
            except StructuredOutputInvalid:
                raise RetrievalFailed("invalid_response") from None
            except ProviderCallError as error:
                logger.warning("Retrieval provider call failed (%s)", error.kind)
                if error.kind == "rate_limited" and retries < len(RATE_LIMIT_WAITS):
                    wait(RATE_LIMIT_WAITS[retries])
                    retries += 1
                    check_stop()  # RunStopped propagates: no retry after a stop request
                    continue
                raise RetrievalFailed(
                    "invalid_response"
                    if error.kind == "invalid_response"
                    else "provider_unavailable"
                ) from None
            except ProviderError:
                logger.warning("Retrieval provider not usable")
                raise RetrievalFailed("provider_unavailable") from None
            except ValidationError as error:
                logger.warning("Retrieval answer invalid: fields=[%s]", validation_detail(error))
                raise RetrievalFailed("invalid_response") from None
            return rank(result.urls, lacking)

    def retrieve(lacking: list[str], focus: str | None) -> list[str]:
        request = prepare(lacking, focus)
        try:
            client = providers.retrieval()
        except ProviderError:
            logger.warning("Retrieval provider not usable")
            raise RetrievalFailed("provider_unavailable") from None
        return send(client, request, lacking)

    def retrieve_focused(lacking: list[str]) -> list[str]:
        if not focuses:
            return retrieve(lacking, None)
        # Prepared in order on this thread; only the provider calls run at the same time.
        prepared: list[RetrievalRequest] = [prepare(lacking, focus) for focus in focuses]
        try:
            client = providers.retrieval()
        except ProviderError:
            logger.warning("Retrieval provider not usable")
            raise RetrievalFailed("provider_unavailable") from None
        budget_ended = threading.Event()
        stopped = threading.Event()

        def run(request: RetrievalRequest) -> list[str]:
            if budget_ended.is_set():
                raise RunBudgetExhausted  # no request starts once the budget is exhausted (#30)
            if stopped.is_set():
                raise RunStopped
            try:
                return send(client, request, lacking)
            except RunBudgetExhausted:
                budget_ended.set()
                raise
            except RunStopped:
                stopped.set()
                raise

        answers: list[list[str]] = []
        failures: list[RetrievalFailed] = []
        exhausted = False
        with ThreadPoolExecutor(max_workers=max(1, min(concurrency, len(prepared)))) as pool:
            futures = [pool.submit(run, request) for request in prepared]
        for future in futures:  # in the configured order, whatever the order of arrival
            try:
                answers.append(future.result())
            except RetrievalFailed as error:
                failures.append(error)
            except RunBudgetExhausted:
                exhausted = True  # what was found is kept
            # RunStopped propagates
        if exhausted and not answers:
            raise RunBudgetExhausted
        merged = RetrievedAddresses(_round_robin(answers))
        merged.failures = failures
        merged.budget_exhausted = exhausted
        return merged

    return retrieve_focused
