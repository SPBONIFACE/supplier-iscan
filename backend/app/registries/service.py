"""Registry candidate search: Wikidata and GLEIF queried together, merged, ranked, cached.

Internal service (no endpoint): the identity agent (#16) calls ``RegistrySearchService.search``.
A registry that fails or times out is skipped and named in the result; the search never raises
because of a registry.
"""

import asyncio
import logging
import time
from typing import Protocol

from app.registries.cache import InMemoryRegistryCache, JsonValue, RegistryCache
from app.registries.gleif import GleifRegistry
from app.registries.gleif_group import GleifGroupClient
from app.registries.http import Clock, Fetch, PoliteHttpClient, Sleep, SlidingWindowRateLimiter
from app.registries.models import (
    RegistryCandidate,
    RegistryName,
    RegistrySearchQuery,
    RegistrySearchResult,
)
from app.registries.ranking import merge_candidates, rank_candidates
from app.registries.settings import RegistrySettings
from app.registries.wikidata import WikidataRegistry

logger = logging.getLogger(__name__)

# Upper bound for one registry's whole search (all its requests and waits), on top of the
# per-request timeout.
REGISTRY_SEARCH_TIMEOUT_FACTOR = 3


class RegistrySource(Protocol):
    name: RegistryName

    async def search(self, name: str) -> list[RegistryCandidate]: ...


def _search_cache_key(registry: RegistryName, name: str) -> str:
    # Only the registry and the supplier name: the hints never reach the cache.
    return f"{registry}:search:{name.casefold()}"


class RegistrySearchService:
    def __init__(
        self,
        wikidata: RegistrySource,
        gleif: RegistrySource,
        cache: RegistryCache,
        registry_timeout_seconds: float,
        gleif_group: GleifGroupClient | None = None,
    ) -> None:
        # Entity and group lookups of #142, on the same polite GLEIF client as the search.
        self.gleif_group = gleif_group
        self._wikidata = wikidata
        self._gleif = gleif
        self._cache = cache
        self._registry_timeout = registry_timeout_seconds

    async def _search_one(
        self, source: RegistrySource, name: str
    ) -> list[RegistryCandidate] | None:
        """Candidates from one registry, or None when it failed."""
        key = _search_cache_key(source.name, name)
        cached = self._cache.get(key)
        if isinstance(cached, list):
            return [RegistryCandidate.model_validate(item) for item in cached]
        try:
            candidates = await asyncio.wait_for(source.search(name), self._registry_timeout)
        except Exception as error:  # noqa: BLE001 - any registry failure is reported, never raised
            logger.warning(
                "registry search failed",
                extra={"registry": source.name, "error_type": type(error).__name__},
            )
            return None
        value: list[JsonValue] = [c.model_dump(mode="json") for c in candidates]
        self._cache.set(key, value)
        return candidates

    async def search(self, query: RegistrySearchQuery) -> RegistrySearchResult:
        wikidata, gleif = await asyncio.gather(
            self._search_one(self._wikidata, query.name),
            self._search_one(self._gleif, query.name),
        )
        failed: list[RegistryName] = []
        if wikidata is None:
            failed.append(self._wikidata.name)
        if gleif is None:
            failed.append(self._gleif.name)
        merged = merge_candidates(wikidata or [], gleif or [])
        ranked = rank_candidates(query, merged)
        return RegistrySearchResult(
            candidates=tuple(ranked),
            failed_registries=tuple(failed),
            website_fallback_offered=not ranked,
        )


def build_registry_service(
    settings: RegistrySettings,
    fetch: Fetch,
    *,
    cache: RegistryCache | None = None,
    clock: Clock = time.monotonic,
    sleep: Sleep = asyncio.sleep,
) -> RegistrySearchService:
    """The service with its polite registry clients, on the given outbound ``fetch``.

    The owner of ``fetch`` (the application's outbound HTTP client) enforces the per-request
    timeout (``settings.timeout_seconds``) and closes it.
    """
    wikidata_http = PoliteHttpClient(
        "wikidata",
        fetch,
        {"User-Agent": settings.user_agent, "Accept": "application/json"},
        max_parallel=settings.wikidata_max_parallel,
        clock=clock,
        sleep=sleep,
    )
    gleif_http = PoliteHttpClient(
        "gleif",
        fetch,
        {"User-Agent": settings.user_agent, "Accept": "application/vnd.api+json"},
        rate_limiter=SlidingWindowRateLimiter(
            settings.gleif_requests_per_minute, 60.0, clock=clock, sleep=sleep
        ),
        clock=clock,
        sleep=sleep,
    )
    registry_cache: RegistryCache = (
        InMemoryRegistryCache(settings.cache_ttl_seconds, clock=clock) if cache is None else cache
    )
    return RegistrySearchService(
        WikidataRegistry(wikidata_http, registry_cache),
        GleifRegistry(gleif_http),
        registry_cache,
        registry_timeout_seconds=settings.timeout_seconds * REGISTRY_SEARCH_TIMEOUT_FACTOR,
        gleif_group=GleifGroupClient(gleif_http, registry_cache),
    )


def build_gleif_group_client(
    settings: RegistrySettings,
    fetch: Fetch,
    cache: RegistryCache,
    *,
    clock: Clock = time.monotonic,
    sleep: Sleep = asyncio.sleep,
) -> GleifGroupClient:
    """The GLEIF entity and group lookups alone (collection), on the polite GLEIF client."""
    http = PoliteHttpClient(
        "gleif",
        fetch,
        {"User-Agent": settings.user_agent, "Accept": "application/vnd.api+json"},
        rate_limiter=SlidingWindowRateLimiter(
            settings.gleif_requests_per_minute, 60.0, clock=clock, sleep=sleep
        ),
        clock=clock,
        sleep=sleep,
    )
    return GleifGroupClient(http, cache)
