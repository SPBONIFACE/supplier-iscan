"""Settings, text normalisation, ranking, merging and cache of the registries module (#14)."""

import asyncio

import httpx2
import pytest

from app.config import ConfigurationError
from app.registries.cache import InMemoryRegistryCache
from app.registries.http import FetchError
from app.registries.httpx2_fetch import Httpx2Fetch
from app.registries.models import RegistryCandidate, RegistrySearchQuery
from app.registries.ranking import merge_candidates, rank_candidates
from app.registries.settings import RegistrySettings, load_registry_settings
from app.registries.text import match_key, normalise_text, search_languages
from tests.registries.support import FakeTime

# --- Settings ------------------------------------------------------------------------------


def test_default_settings_respect_the_registry_limits() -> None:
    settings = load_registry_settings({})

    assert settings.wikidata_max_parallel == 5
    assert settings.gleif_requests_per_minute < 60
    assert settings.cache_ttl_seconds > 0
    assert settings.user_agent.startswith("SupplierIScan/")
    assert "github.com/SPBONIFACE/supplier-iscan" in settings.user_agent


def test_settings_are_read_from_the_environment() -> None:
    settings = load_registry_settings(
        {
            "REGISTRY_CONTACT": "ops@example.org",
            "REGISTRY_CACHE_TTL_SECONDS": "600",
            "REGISTRY_TIMEOUT_SECONDS": "4.5",
            "GLEIF_REQUESTS_PER_MINUTE": "30",
            "WIKIDATA_MAX_PARALLEL": "3",
        }
    )

    assert settings == RegistrySettings(
        contact="ops@example.org",
        cache_ttl_seconds=600,
        timeout_seconds=4.5,
        gleif_requests_per_minute=30,
        wikidata_max_parallel=3,
    )
    assert "ops@example.org" in settings.user_agent


@pytest.mark.parametrize(
    "environ",
    [
        {"GLEIF_REQUESTS_PER_MINUTE": "60"},
        {"GLEIF_REQUESTS_PER_MINUTE": "0"},
        {"WIKIDATA_MAX_PARALLEL": "6"},
        {"REGISTRY_CACHE_TTL_SECONDS": "0"},
        {"REGISTRY_CACHE_TTL_SECONDS": "a day"},
        {"REGISTRY_TIMEOUT_SECONDS": "-1"},
        {"REGISTRY_CONTACT": "bad (contact)"},
    ],
)
def test_unacceptable_settings_stop_startup(environ: dict[str, str]) -> None:
    with pytest.raises(ConfigurationError):
        load_registry_settings(environ)


# --- Text ----------------------------------------------------------------------------------


def test_normalise_text_composes_and_collapses_whitespace() -> None:
    assert normalise_text("  Société   Générale ") == "Société Générale"


def test_match_key_folds_latin_accents_and_case_only() -> None:
    assert match_key("SOCIÉTÉ GÉNÉRALE S.A.") == match_key("societe generale s a")
    # The voiced kana ジ must not become シ.
    assert match_key("ジ") != match_key("シ")
    assert match_key("トヨタ自動車") == "トヨタ自動車"


def test_search_languages_follow_the_script_of_the_name() -> None:
    assert search_languages("Société Générale") == ("en", "fr", "de")
    assert search_languages("トヨタ自動車") == ("ja", "en")
    assert search_languages("三菱商事") == ("zh", "ja", "en")
    assert search_languages("삼성전자") == ("ko", "en")
    assert search_languages("Газпром") == ("ru", "en")


# --- Merge and ranking ---------------------------------------------------------------------


def candidate(**fields: object) -> RegistryCandidate:
    return RegistryCandidate.model_validate({"registries": ("wikidata",), **fields})


def test_merge_on_lei_keeps_one_record_with_both_sources() -> None:
    wikidata = [
        candidate(name="Acme", wikidata_id="Q1", lei="LEI1", website="https://acme.example")
    ]
    gleif = [
        candidate(
            name="ACME SA", legal_name="ACME SA", lei="LEI1", country="FR", registries=("gleif",)
        ),
        candidate(name="ACME GmbH", legal_name="ACME GmbH", lei="LEI2", registries=("gleif",)),
    ]

    merged = merge_candidates(wikidata, gleif)

    assert [(c.wikidata_id, c.lei, c.registries) for c in merged] == [
        ("Q1", "LEI1", ("wikidata", "gleif")),
        (None, "LEI2", ("gleif",)),
    ]
    assert merged[0].website == "https://acme.example"
    assert merged[0].legal_name == "ACME SA"
    assert merged[0].country == "FR"


def test_ranking_never_drops_or_duplicates_a_candidate() -> None:
    pool = [
        candidate(name="Acme", wikidata_id="Q1", country="FR"),
        candidate(name="Acme", wikidata_id="Q2", country="DE"),
        candidate(name="Acme Holdings", wikidata_id="Q3"),
    ]
    query = RegistrySearchQuery(
        name="Acme", country_hint="US", website_hint="nowhere.example", sector_hint="mining"
    )

    ranked = rank_candidates(query, pool)

    assert sorted(c.wikidata_id or "" for c in ranked) == ["Q1", "Q2", "Q3"]


def test_country_hint_puts_the_matching_homonym_first() -> None:
    pool = [
        candidate(name="Acme", wikidata_id="Q1", country="FR"),
        candidate(name="Acme", wikidata_id="Q2", country="DE"),
    ]

    plain = rank_candidates(RegistrySearchQuery(name="Acme"), pool)
    hinted = rank_candidates(RegistrySearchQuery(name="Acme", country_hint="de"), pool)

    assert [c.wikidata_id for c in plain] == ["Q1", "Q2"]
    assert [c.wikidata_id for c in hinted] == ["Q2", "Q1"]


def test_website_hint_matches_subdomains_and_ignores_www() -> None:
    pool = [
        candidate(name="Acme", wikidata_id="Q1", website="https://www.acme-one.example/"),
        candidate(name="Acme", wikidata_id="Q2", website="https://acme-two.example"),
    ]

    hinted = rank_candidates(
        RegistrySearchQuery(name="Acme", website_hint="shop.acme-two.example"), pool
    )

    assert hinted[0].wikidata_id == "Q2"


def test_sector_hint_raises_a_matching_industry() -> None:
    pool = [
        candidate(name="Acme", wikidata_id="Q1", industries=("retail",)),
        candidate(name="Acme", wikidata_id="Q2", industries=("steel industry",)),
    ]

    hinted = rank_candidates(RegistrySearchQuery(name="Acme", sector_hint="Steel"), pool)

    assert hinted[0].wikidata_id == "Q2"


def test_a_candidate_needs_an_identifier() -> None:
    with pytest.raises(ValueError):
        candidate(name="Acme")


# --- Cache ---------------------------------------------------------------------------------


def test_cache_entries_expire_and_the_oldest_are_evicted() -> None:
    time = FakeTime()
    cache = InMemoryRegistryCache(10, max_entries=2, clock=time.clock)

    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("a") is None
    assert cache.get("b") == 2

    time.now += 10
    assert cache.get("c") is None
    assert len(cache) == 1


def test_cache_rejects_a_non_positive_duration() -> None:
    with pytest.raises(ValueError):
        InMemoryRegistryCache(0)


# --- httpx2 adapter (replaced by the guarded client of #15) --------------------------------


def test_httpx2_fetch_sends_params_and_headers_and_returns_the_body() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"ok": True}, headers={"Retry-After": "3"})

    async def run() -> tuple[int, bytes, str | None]:
        fetch = Httpx2Fetch(5.0, transport=httpx2.MockTransport(handler))
        response = await fetch(
            "https://www.wikidata.org/w/api.php",
            {"search": "Société Générale"},
            {"User-Agent": "SupplierIScan/test (contact)"},
        )
        await fetch.aclose()
        return response.status_code, response.body, response.headers.get("retry-after")

    status, body, retry_after = asyncio.run(run())

    assert status == 200 and body == b'{"ok":true}'
    assert retry_after == "3"
    assert seen[0].headers["User-Agent"] == "SupplierIScan/test (contact)"
    assert seen[0].url.params["search"] == "Société Générale"


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (httpx2.ConnectError("refused"), "unreachable"),
        (httpx2.ReadTimeout("slow"), "timeout"),
    ],
)
def test_httpx2_fetch_maps_transport_errors(error: Exception, kind: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error

    async def run() -> None:
        fetch = Httpx2Fetch(5.0, transport=httpx2.MockTransport(handler))
        try:
            await fetch("https://api.gleif.org/api/v1/lei-records", {}, {})
        finally:
            await fetch.aclose()

    with pytest.raises(FetchError) as raised:
        asyncio.run(run())
    assert raised.value.kind == kind
