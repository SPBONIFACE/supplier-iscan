"""Registry candidate search against recorded Wikidata and GLEIF fixtures (issue #14)."""

import asyncio
import unicodedata
from collections import Counter

import pytest
from pydantic import ValidationError

from app.registries.http import FetchedResponse
from app.registries.models import RegistrySearchQuery, RegistrySearchResult
from app.registries.settings import RegistrySettings
from tests.registries.support import (
    EMPTY_GLEIF_SEARCH,
    EMPTY_WIKIDATA_SEARCH,
    GLEIF_HOST,
    WIKIDATA_HOST,
    WIKIDATA_TOO_BUSY,
    FakeTime,
    RecordedRegistries,
    SentRequest,
    answering,
    failing,
    json_response,
    load_exchanges,
    make_service,
)

SOCIETE_GENERALE_QID = "Q270363"
SOCIETE_GENERALE_LEI = "O2RNE8IBXP4R0TD8PU41"
TOYOTA_QID = "Q53268"
TOYOTA_LEI = "5493006W3QUS5LMH6R84"


def search(
    fetch: RecordedRegistries,
    query: RegistrySearchQuery,
    time: FakeTime | None = None,
    settings: RegistrySettings | None = None,
) -> RegistrySearchResult:
    service = make_service(fetch, time=time, settings=settings)
    return asyncio.run(service.search(query))


def ids(result: RegistrySearchResult) -> list[tuple[str | None, str | None]]:
    return [(c.wikidata_id, c.lei) for c in result.candidates]


def position_of_societe_generale(result: RegistrySearchResult) -> int:
    return next(i for i, c in enumerate(result.candidates) if c.wikidata_id == SOCIETE_GENERALE_QID)


# --- Candidates, fields, merge on LEI -------------------------------------------------------


def test_candidates_carry_registry_fields_and_their_source() -> None:
    fetch = RecordedRegistries(load_exchanges("societe_generale"))

    result = search(fetch, RegistrySearchQuery(name="Société Générale"))

    assert fetch.unmatched == []
    assert result.failed_registries == ()
    assert result.website_fallback_offered is False
    top = result.candidates[0]
    assert top.name == "Société Générale"
    assert top.wikidata_id == SOCIETE_GENERALE_QID
    assert top.lei == SOCIETE_GENERALE_LEI
    assert top.registries == ("wikidata", "gleif")
    assert top.website == "https://www.societegenerale.com/"
    assert top.country == "FR"
    assert top.country_name == "France"
    assert top.industries
    assert top.legal_form
    assert top.legal_form_code
    assert top.legal_name == "SOCIETE GENERALE"
    assert top.registered_address and "PARIS" in top.registered_address
    # Every candidate names its registry and has at least one identifier.
    for candidate in result.candidates:
        assert set(candidate.registries) <= {"wikidata", "gleif"}
        assert candidate.wikidata_id or candidate.lei
    sources = {c.registries for c in result.candidates}
    assert ("wikidata",) in sources and ("gleif",) in sources


def test_company_found_in_both_registries_appears_once() -> None:
    fetch = RecordedRegistries(load_exchanges("societe_generale"))

    result = search(fetch, RegistrySearchQuery(name="Société Générale"))

    leis = Counter(c.lei for c in result.candidates if c.lei)
    qids = Counter(c.wikidata_id for c in result.candidates if c.wikidata_id)
    assert leis[SOCIETE_GENERALE_LEI] == 1
    assert qids[SOCIETE_GENERALE_QID] == 1
    assert all(count == 1 for count in leis.values())
    assert all(count == 1 for count in qids.values())


# --- Hints change the ranking only ----------------------------------------------------------


def test_wrong_country_hint_lowers_the_true_company_but_keeps_every_candidate() -> None:
    exchanges = load_exchanges("societe_generale")

    plain = search(RecordedRegistries(exchanges), RegistrySearchQuery(name="Société Générale"))
    hinted = search(
        RecordedRegistries(exchanges),
        RegistrySearchQuery(name="Société Générale", country_hint="CA"),
    )

    assert position_of_societe_generale(plain) == 0
    assert position_of_societe_generale(hinted) > position_of_societe_generale(plain)
    assert len(hinted.candidates) == len(plain.candidates)
    assert sorted(ids(hinted), key=str) == sorted(ids(plain), key=str)
    assert hinted.candidates[0].country == "CA"


def test_country_hint_by_name_is_understood() -> None:
    exchanges = load_exchanges("societe_generale")

    plain = search(RecordedRegistries(exchanges), RegistrySearchQuery(name="Société Générale"))
    hinted = search(
        RecordedRegistries(exchanges),
        RegistrySearchQuery(name="Société Générale", country_hint="Belgium"),
    )

    assert hinted.candidates[0].country == "BE"
    assert position_of_societe_generale(hinted) > 0
    assert sorted(ids(hinted), key=str) == sorted(ids(plain), key=str)


@pytest.mark.parametrize(
    "hints",
    [
        {"website_hint": "https://www.societegenerale.com/fr/"},
        {"website_hint": "example.org"},
        {"sector_hint": "bank"},
        {"sector_hint": "railway"},
        {"country_hint": "FR", "website_hint": "sg.fr", "sector_hint": "press"},
    ],
)
def test_any_hint_keeps_the_same_candidates(hints: dict[str, str]) -> None:
    exchanges = load_exchanges("societe_generale")

    plain = search(RecordedRegistries(exchanges), RegistrySearchQuery(name="Société Générale"))
    hinted = search(
        RecordedRegistries(exchanges), RegistrySearchQuery(name="Société Générale", **hints)
    )

    assert len(hinted.candidates) == len(plain.candidates)
    assert sorted(ids(hinted), key=str) == sorted(ids(plain), key=str)


def test_wrong_website_hint_lowers_and_right_one_keeps_the_true_company_first() -> None:
    exchanges = load_exchanges("societe_generale")

    right = search(
        RecordedRegistries(exchanges),
        RegistrySearchQuery(name="Société Générale", website_hint="societegenerale.com"),
    )
    wrong = search(
        RecordedRegistries(exchanges),
        RegistrySearchQuery(name="Société Générale", website_hint="https://www.sgae.es"),
    )

    assert position_of_societe_generale(right) == 0
    assert position_of_societe_generale(wrong) > 0


def test_hints_are_never_sent_to_the_registries() -> None:
    fetch = RecordedRegistries(load_exchanges("societe_generale"))

    search(
        fetch,
        RegistrySearchQuery(
            name="Société Générale",
            country_hint="Canada",
            website_hint="hint-site.example",
            sector_hint="hint-sector",
        ),
    )

    sent = " ".join(str(r.params) for r in fetch.sent)
    assert "Canada" not in sent and "hint-site" not in sent and "hint-sector" not in sent
    assert fetch.unmatched == []


# --- Politeness -----------------------------------------------------------------------------


def test_every_request_carries_a_descriptive_user_agent_with_a_contact() -> None:
    fetch = RecordedRegistries(load_exchanges("societe_generale"))
    settings = RegistrySettings(contact="procurement-ops@example.org")

    search(fetch, RegistrySearchQuery(name="Société Générale"), settings=settings)

    assert fetch.sent_to(WIKIDATA_HOST) and fetch.sent_to(GLEIF_HOST)
    for request in fetch.sent:
        user_agent = request.headers["User-Agent"]
        assert user_agent.startswith("SupplierIScan/")
        assert "procurement-ops@example.org" in user_agent


def test_default_user_agent_names_the_project() -> None:
    fetch = RecordedRegistries(load_exchanges("societe_generale"))

    search(fetch, RegistrySearchQuery(name="Société Générale"))

    for request in fetch.sent:
        assert "github.com/SPBONIFACE/supplier-iscan" in request.headers["User-Agent"]


def test_wikidata_runs_at_most_five_requests_in_parallel() -> None:
    # Each answer takes a while, so concurrent requests overlap; the Société Générale search fans
    # out over 3 search languages and 5 country lookups.
    fetch = RecordedRegistries(load_exchanges("societe_generale"), delay_seconds=0.01)

    result = search(fetch, RegistrySearchQuery(name="Société Générale"))

    assert result.failed_registries == ()
    assert len(fetch.sent_to(WIKIDATA_HOST)) > 5
    assert fetch.max_in_flight[WIKIDATA_HOST] == 5


def test_wikidata_429_waits_for_retry_after_before_retrying() -> None:
    first_search: list[SentRequest] = []

    def busy_once(request: SentRequest) -> FetchedResponse | None:
        if request.params.get("action") == "wbsearchentities" and not first_search:
            first_search.append(request)
            return json_response(429, {}, {"retry-after": "7"})
        return None

    fetch = RecordedRegistries(
        load_exchanges("societe_generale"), overrides={WIKIDATA_HOST: busy_once}
    )
    time = FakeTime()

    result = search(fetch, RegistrySearchQuery(name="Société Générale"), time=time)

    assert result.failed_registries == ()
    assert 7.0 in time.sleeps
    retried = [r for r in fetch.sent_to(WIKIDATA_HOST) if r.params == first_search[0].params]
    assert len(retried) == 2
    assert result.candidates[0].wikidata_id == SOCIETE_GENERALE_QID


def test_wikidata_429_with_a_too_long_retry_after_skips_the_registry() -> None:
    fetch = RecordedRegistries(
        load_exchanges("societe_generale"),
        overrides={WIKIDATA_HOST: answering(429, {}, {"retry-after": "3600"})},
    )
    time = FakeTime()

    result = search(fetch, RegistrySearchQuery(name="Société Générale"), time=time)

    assert result.failed_registries == ("wikidata",)
    assert 3600.0 not in time.sleeps
    assert result.candidates and all(c.registries == ("gleif",) for c in result.candidates)


def test_gleif_is_throttled_below_60_requests_per_minute() -> None:
    fetch = RecordedRegistries(
        overrides={
            WIKIDATA_HOST: answering(200, EMPTY_WIKIDATA_SEARCH),
            GLEIF_HOST: answering(200, EMPTY_GLEIF_SEARCH),
        }
    )
    time = FakeTime()
    service = make_service(fetch, time=time)
    started: list[float] = []

    async def run() -> None:
        original = fetch.overrides[GLEIF_HOST]

        def timed(request: SentRequest) -> FetchedResponse | None:
            started.append(time.now)
            answer = original(request)
            assert answer is None or isinstance(answer, FetchedResponse)
            return answer

        fetch.overrides[GLEIF_HOST] = timed
        # 130 different names, so that the cache never answers.
        await asyncio.gather(
            *(service.search(RegistrySearchQuery(name=f"Supplier {n}")) for n in range(130))
        )

    asyncio.run(run())

    assert len(started) == 130
    for index, moment in enumerate(started):
        in_window = [t for t in started[index:] if t < moment + 60.0]
        assert len(in_window) < 60


# --- Cache ----------------------------------------------------------------------------------


def test_repeated_identical_search_makes_no_http_request() -> None:
    fetch = RecordedRegistries(load_exchanges("societe_generale"))
    service = make_service(fetch)
    query = RegistrySearchQuery(name="Société Générale")

    async def run() -> tuple[RegistrySearchResult, RegistrySearchResult, int]:
        first = await service.search(query)
        count = len(fetch.sent)
        second = await service.search(query)
        return first, second, count

    first, second, count_after_first = asyncio.run(run())

    assert count_after_first > 0
    assert len(fetch.sent) == count_after_first
    assert second == first


def test_cached_search_with_other_hints_makes_no_http_request() -> None:
    fetch = RecordedRegistries(load_exchanges("societe_generale"))
    service = make_service(fetch)

    async def run() -> RegistrySearchResult:
        await service.search(RegistrySearchQuery(name="Société Générale"))
        fetch.sent.clear()
        return await service.search(RegistrySearchQuery(name="Société Générale", country_hint="CA"))

    hinted = asyncio.run(run())

    assert fetch.sent == []
    assert hinted.candidates[0].country == "CA"


def test_cache_expires_after_the_configured_duration() -> None:
    fetch = RecordedRegistries(load_exchanges("societe_generale"))
    time = FakeTime()
    service = make_service(fetch, time=time, settings=RegistrySettings(cache_ttl_seconds=3600))
    query = RegistrySearchQuery(name="Société Générale")

    async def run() -> tuple[int, int]:
        await service.search(query)
        time.now += 3599
        fetch.sent.clear()
        await service.search(query)
        within = len(fetch.sent)
        time.now += 2
        await service.search(query)
        return within, len(fetch.sent)

    within_ttl, after_ttl = asyncio.run(run())

    assert within_ttl == 0
    assert after_ttl > 0


def test_cache_holds_registry_public_data_only() -> None:
    from app.registries.cache import InMemoryRegistryCache
    from app.registries.service import build_registry_service

    fetch = RecordedRegistries(load_exchanges("societe_generale"))
    time = FakeTime()
    cache = InMemoryRegistryCache(3600, clock=time.clock)
    service = build_registry_service(
        RegistrySettings(), fetch, cache=cache, clock=time.clock, sleep=time.sleep
    )

    asyncio.run(
        service.search(
            RegistrySearchQuery(
                name="Société Générale",
                country_hint="hint-country",
                website_hint="hint-site.example",
                sector_hint="hint-sector",
            )
        )
    )

    entries = cache.items()
    assert entries
    dumped = repr(entries)
    for hint in ("hint-country", "hint-site", "hint-sector"):
        assert hint not in dumped
    for key, _ in entries:
        assert key.split(":", 1)[0] in {"wikidata", "gleif"}


def test_failed_registry_is_not_cached() -> None:
    fetch = RecordedRegistries(
        load_exchanges("societe_generale"), overrides={GLEIF_HOST: failing("unreachable")}
    )
    service = make_service(fetch)
    query = RegistrySearchQuery(name="Société Générale")

    async def run() -> RegistrySearchResult:
        await service.search(query)
        del fetch.overrides[GLEIF_HOST]
        fetch.sent.clear()
        return await service.search(query)

    second = asyncio.run(run())

    assert second.failed_registries == ()
    assert fetch.sent_to(GLEIF_HOST)
    assert fetch.sent_to(WIKIDATA_HOST) == []


# --- One or both registries down ------------------------------------------------------------


@pytest.mark.parametrize("kind", ["unreachable", "timeout"])
def test_gleif_down_returns_wikidata_candidates_and_names_gleif(kind: str) -> None:
    fetch = RecordedRegistries(
        load_exchanges("societe_generale"), overrides={GLEIF_HOST: failing(kind)}
    )

    result = search(fetch, RegistrySearchQuery(name="Société Générale"))

    assert result.failed_registries == ("gleif",)
    assert result.website_fallback_offered is False
    assert result.candidates
    assert all(c.registries == ("wikidata",) for c in result.candidates)


@pytest.mark.parametrize(
    "override",
    [
        failing("unreachable"),
        failing("timeout"),
        answering(500, {"error": "internal"}),
        answering(200, WIKIDATA_TOO_BUSY),
    ],
    ids=["unreachable", "timeout", "http-500", "error-body"],
)
def test_wikidata_down_returns_gleif_candidates_and_names_wikidata(override: object) -> None:
    fetch = RecordedRegistries(
        load_exchanges("societe_generale"),
        overrides={WIKIDATA_HOST: override},  # type: ignore[dict-item]
    )

    result = search(fetch, RegistrySearchQuery(name="Société Générale"))

    assert result.failed_registries == ("wikidata",)
    assert result.candidates
    assert all(c.registries == ("gleif",) for c in result.candidates)


def test_invalid_json_from_a_registry_counts_as_a_failure() -> None:
    def not_json(request: SentRequest) -> FetchedResponse:
        return FetchedResponse(status_code=200, body=b"<html>maintenance</html>")

    fetch = RecordedRegistries(load_exchanges("societe_generale"), overrides={GLEIF_HOST: not_json})

    result = search(fetch, RegistrySearchQuery(name="Société Générale"))

    assert result.failed_registries == ("gleif",)
    assert result.candidates


def test_a_registry_slower_than_the_time_limit_is_skipped() -> None:
    async def hangs(request: SentRequest) -> FetchedResponse:
        await asyncio.sleep(5)
        raise AssertionError("never answered")

    fetch = RecordedRegistries(load_exchanges("societe_generale"), overrides={GLEIF_HOST: hangs})
    settings = RegistrySettings(timeout_seconds=0.02)

    result = search(fetch, RegistrySearchQuery(name="Société Générale"), settings=settings)

    assert result.failed_registries == ("gleif",)
    assert result.candidates


def test_both_registries_down_returns_no_candidate_and_offers_the_website_fallback() -> None:
    fetch = RecordedRegistries(
        overrides={WIKIDATA_HOST: failing("unreachable"), GLEIF_HOST: failing("timeout")}
    )

    result = search(fetch, RegistrySearchQuery(name="Société Générale"))

    assert result.candidates == ()
    assert result.failed_registries == ("wikidata", "gleif")
    assert result.website_fallback_offered is True


# --- Unicode and validation -----------------------------------------------------------------


def test_accented_name_is_searched_and_returned_intact_after_normalisation() -> None:
    decomposed = unicodedata.normalize("NFD", "Société Générale")
    assert decomposed != "Société Générale"
    fetch = RecordedRegistries(load_exchanges("societe_generale"))

    result = search(fetch, RegistrySearchQuery(name=f"  {decomposed} "))

    assert fetch.unmatched == []
    searched = {r.params.get("search") or r.params.get("filter[entity.names]") for r in fetch.sent}
    assert "Société Générale" in searched
    assert result.candidates[0].name == "Société Générale"
    for candidate in result.candidates:
        assert unicodedata.is_normalized("NFC", candidate.name)


def test_japanese_name_is_searched_and_returned_intact() -> None:
    fetch = RecordedRegistries(load_exchanges("toyota_japanese"))

    result = search(fetch, RegistrySearchQuery(name="トヨタ自動車"))

    assert fetch.unmatched == []
    assert result.failed_registries == ()
    languages = {r.params.get("language") for r in fetch.sent_to(WIKIDATA_HOST)} - {None}
    assert {"ja", "en"} <= languages
    top = result.candidates[0]
    assert top.name == "トヨタ自動車"
    assert top.legal_name == "トヨタ自動車株式会社"
    assert top.wikidata_id == TOYOTA_QID
    assert top.lei == TOYOTA_LEI
    assert top.registries == ("wikidata", "gleif")
    assert top.country == "JP"


@pytest.mark.parametrize("name", ["", "   ", "\t\n", "　"])
def test_empty_or_whitespace_name_is_a_validation_error(name: str) -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        RegistrySearchQuery(name=name)


def test_oversized_name_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        RegistrySearchQuery(name="x" * 201)


def test_blank_hints_are_ignored() -> None:
    query = RegistrySearchQuery(name="Acme", country_hint="  ", website_hint="", sector_hint=None)

    assert query.country_hint is None and query.website_hint is None
