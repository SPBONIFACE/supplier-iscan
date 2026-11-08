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
from dataclasses import dataclass

from pydantic import ValidationError

from app.collection.collector import RetrieveFn
from app.collection.failures import RetrievalFailed
from app.collection.pages import classify
from app.collection.source_store import IdentityRedaction
from app.countries import country_name
from app.prompts import PromptSet
from app.providers import (
    ProviderCallError,
    ProviderError,
    Providers,
    RetrievalRequest,
    RetrievedUrl,
    StructuredOutputInvalid,
)
from app.providers.failures import validation_detail
from app.providers.metering import CallContext
from app.redaction import RedactionGate

logger = logging.getLogger(__name__)

PROMPT_ID = "retrieval"


# Asked when the website gave every page kind: sources other than the supplier's own pages.
INDEPENDENT_REQUEST = (
    "No field group lacks evidence on the supplier's own website. Return independent sources "
    "only: official registers, certification bodies, news and trade press. Not further pages "
    "of the supplier's own website."
)


@dataclass(frozen=True)
class IdentityRecord:
    legal_name: str
    website: str | None
    country: str | None


def _supplier_text(identity: IdentityRecord, lacking: list[str]) -> str:
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
    return "\n".join(lines)


def rank(urls: list[RetrievedUrl], lacking: list[str]) -> list[str]:
    """The addresses, those whose address or snippet points at a lacking group first. The snippet
    is used here only and is dropped."""
    wanted = set(lacking)
    scored = [(0 if classify(item.url, item.snippet) in wanted else 1, item.url) for item in urls]
    return [url for _score, url in sorted(scored, key=lambda pair: pair[0])]


def make_retriever(
    providers: Providers,
    prompts: PromptSet,
    gate: RedactionGate,
    redaction: IdentityRedaction,
    identity: IdentityRecord,
    context: CallContext,
) -> RetrieveFn:
    def retrieve(lacking: list[str]) -> list[str]:
        rendered = prompts.render(PROMPT_ID, {"supplier": _supplier_text(identity, lacking)})
        # Redacted before the call; a failure raises RedactionUnavailable and nothing is sent.
        query = gate.redact(
            rendered.data,
            person_names=redaction.person_names,
            addresses=redaction.addresses,
            company_names=redaction.company_names,
        )
        try:
            client = providers.retrieval()
            result = client.retrieve(RetrievalRequest(rendered.instructions, query), context)
        except StructuredOutputInvalid:
            raise RetrievalFailed("invalid_response") from None
        except ProviderCallError as error:
            logger.warning("Retrieval provider call failed (%s)", error.kind)
            raise RetrievalFailed(
                "invalid_response" if error.kind == "invalid_response" else "provider_unavailable"
            ) from None
        except ProviderError:
            logger.warning("Retrieval provider not usable")
            raise RetrievalFailed("provider_unavailable") from None
        except ValidationError as error:
            logger.warning("Retrieval answer invalid: fields=[%s]", validation_detail(error))
            raise RetrievalFailed("invalid_response") from None
        return rank(result.urls, lacking)

    return retrieve
