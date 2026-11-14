"""Helpers for the identity tests: a scripted registry search, a fake model, an application on them.

No real network and no real provider key: the registries answer from a table, the model is the
fake structuring adapter of `app.providers.fake`, the supplier's website is a mock site.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx2
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.config import Settings
from app.http_client import GuardedClient
from app.identity.services import AsyncRunner, IdentityServices
from app.providers import Providers
from app.providers.fake import FakeRetrievalAdapter, FakeStructuringAdapter, fake_adapters
from app.registries import RegistryCandidate, RegistrySearchQuery, RegistrySearchResult
from tests.http_client.support import PUBLIC_V4, MockSite, StubResolver
from tests.providers.support import SENTINEL_KEY, catalogue, config, make_meter
from tests.support import make_client

WEBSITE_HOST = "acme.example"
Scripted = RegistrySearchResult | Callable[[RegistrySearchQuery], RegistrySearchResult]


def candidate(name: str = "Acme Supplies SA", **values: Any) -> RegistryCandidate:
    fields: dict[str, Any] = {
        "name": name,
        "legal_name": name,
        "description": "Industrial supplies",
        "website": f"https://{WEBSITE_HOST}",
        "country": "FR",
        "country_name": "France",
        "industries": ("Wholesale",),
        "legal_form": "Societe anonyme",
        "wikidata_id": "Q1",
        "lei": "529900ACME00000000AA",
        "registries": ("wikidata", "gleif"),
    }
    fields.update(values)
    return RegistryCandidate(**fields)


def found(*candidates: RegistryCandidate, failed: tuple[str, ...] = ()) -> RegistrySearchResult:
    return RegistrySearchResult(
        candidates=candidates,
        failed_registries=failed,  # type: ignore[arg-type]
        website_fallback_offered=not candidates,
    )


class FakeRegistries:
    """Answers each search from a script, and records the queries it received."""

    def __init__(self, *results: Scripted) -> None:
        self._results = list(results)
        self.queries: list[RegistrySearchQuery] = []

    async def search(self, query: RegistrySearchQuery) -> RegistrySearchResult:
        self.queries.append(query)
        # The last answer is repeated once the script is used up.
        scripted = self._results.pop(0) if len(self._results) > 1 else self._results[0]
        return scripted(query) if callable(scripted) else scripted


def proposal(candidate_id: str | None, **values: Any) -> str:
    """The JSON a model returns for an `IdentityProposal`."""
    return json.dumps({"candidate_id": candidate_id, "confidence": 0.9, **values})


@dataclass
class Harness:
    client: TestClient
    model: FakeStructuringAdapter
    registries: FakeRegistries
    site: MockSite
    providers: Providers
    services: IdentityServices
    web: FakeRetrievalAdapter
    resolver: StubResolver = field(default_factory=lambda: StubResolver({}))


def make_harness(
    engine: Engine,
    settings: Settings,
    registries: FakeRegistries,
    model_outputs: list[Any] | None = None,
    pages: dict[tuple[str, str], httpx2.Response] | None = None,
    web_results: list[Any] | None = None,
) -> Harness:
    model = FakeStructuringAdapter(list(model_outputs or []))
    # The identity web search: unscripted, a call fails (and the chat goes on without it).
    web = FakeRetrievalAdapter(list(web_results or []))
    cat = catalogue(config("primary"))
    providers = Providers(
        cat,
        {"GEMINI_API_KEY": SENTINEL_KEY},
        fake_adapters(cat, model, web),
        meter=make_meter(),
    )
    site = MockSite(pages or {(WEBSITE_HOST, "/"): httpx2.Response(200, text="Acme")})
    resolver = StubResolver({WEBSITE_HOST: [PUBLIC_V4]})
    services = IdentityServices(
        registries=registries,
        runner=AsyncRunner(),
        http=GuardedClient(resolver=resolver, inner_transport=site.transport),
    )
    client = make_client(settings=settings, engine=engine, providers=providers)
    client.app.state.identity_services = services  # type: ignore[attr-defined]
    return Harness(client, model, registries, site, providers, services, web, resolver)
