"""#134: the retrieval step runs on every run, and asks for independent sources."""

import httpx2

from app.collection.collector import RetrieveFn
from app.collection.failures import RetrievalFailed
from app.collection.retrieval import IdentityRecord, _supplier_text
from app.collection.settings import CollectionSettings
from tests.collection.support import HOST, OTHER, html, make_collector

NAME = "Acme Supplies SA"
SITE = f"https://{HOST}/"


def full_site() -> dict[tuple[str, str], httpx2.Response]:
    """A website that has the about, sustainability and quality pages."""
    pages = {
        (HOST, "/"): html(
            "<p>Acme Supplies SA</p><a href='/about'>About</a>"
            "<a href='/sustainability'>Sustainability</a><a href='/quality'>Quality</a>"
            "<a href='/locations'>Locations</a>"
        )
    }
    for path in ("about", "sustainability", "quality", "locations"):
        pages[(HOST, f"/{path}")] = html(f"<p>Acme Supplies SA {path}</p>")
    return pages


def test_retrieval_runs_also_when_no_page_kind_is_lacking() -> None:
    asked: list[list[str]] = []

    def retrieve(lacking: list[str]) -> list[str]:
        asked.append(lacking)
        return [f"https://{OTHER}/register"]

    pages = {**full_site(), (OTHER, "/register"): html("<p>Register of Acme Supplies SA</p>")}
    collector, _site, stored, _sleeps, _ = make_collector(pages)

    collector.collect(SITE, NAME, retrieve)

    assert len(asked) == 1 and asked[0] == []
    assert f"https://{OTHER}/register" in [r.url for r in stored]


def test_the_provider_is_asked_for_independent_sources_when_nothing_lacks() -> None:
    identity = IdentityRecord("Acme", "https://acme.example", "DE")

    assert "independent sources" in _supplier_text(identity, [])
    assert "lacking evidence: about" in _supplier_text(identity, ["about"])


def test_at_most_one_address_on_the_suppliers_own_domain_when_the_website_gave_sources() -> None:
    settings = CollectionSettings(min_delay_seconds=0, backoff_seconds=0, max_retrieval_urls=3)
    pages = {
        (HOST, "/"): html("<p>Acme Supplies SA</p>"),
        (HOST, "/a"): html("<p>own a</p>"),
        (HOST, "/b"): html("<p>own b</p>"),
        (OTHER, "/x"): html("<p>other x</p>"),
        (OTHER, "/y"): html("<p>other y</p>"),
    }
    collector, _site, stored, _sleeps, _ = make_collector(pages, settings)
    urls = [f"https://{HOST}/a", f"https://{HOST}/b", f"https://{OTHER}/x", f"https://{OTHER}/y"]

    collector.collect(SITE, NAME, lambda _lacking: urls)

    assert [r.url for r in stored[1:]] == [
        f"https://{HOST}/a",
        f"https://{OTHER}/x",
        f"https://{OTHER}/y",
    ]


def test_own_domain_addresses_are_not_capped_when_the_website_gave_no_source() -> None:
    pages = {(HOST, "/a"): html("<p>own a</p>"), (HOST, "/b"): html("<p>own b</p>")}
    collector, _site, stored, _sleeps, _ = make_collector(pages)
    retrieve: RetrieveFn = lambda _lacking: [f"https://{HOST}/a", f"https://{HOST}/b"]  # noqa: E731

    collector.collect(SITE, NAME, retrieve)

    assert len(stored) == 2


def test_the_default_number_of_retrieval_addresses_is_twelve() -> None:
    assert CollectionSettings().max_retrieval_urls == 12


def test_a_failing_retrieval_with_nothing_lacking_keeps_the_website_sources() -> None:
    def broken(_lacking: list[str]) -> list[str]:
        raise RetrievalFailed("provider_unavailable")

    collector, _site, stored, _sleeps, _ = make_collector(full_site())

    result = collector.collect(SITE, NAME, broken)

    assert len(stored) == 5
    assert [f.kind for f in result.failures if f.strategy == "retrieval"] == [
        "provider_unavailable"
    ]


def _outside_after_own(
    own: int, outside: int
) -> tuple[dict[tuple[str, str], httpx2.Response], list[str]]:
    pages: dict[tuple[str, str], httpx2.Response] = {(HOST, "/"): html("<p>Acme Supplies SA</p>")}
    urls = []
    for i in range(own):
        pages[(HOST, f"/o{i}")] = html(f"<p>own {i}</p>")
        urls.append(f"https://{HOST}/o{i}")
    for i in range(outside):
        pages[(OTHER, f"/x{i}")] = html(f"<p>other {i}</p>")
        urls.append(f"https://{OTHER}/x{i}")
    return pages, urls


def test_outside_addresses_after_fifteen_own_ones_are_fetched() -> None:
    settings = CollectionSettings(min_delay_seconds=0, backoff_seconds=0, max_domains=50)
    pages, urls = _outside_after_own(15, 5)
    collector, _site, stored, _sleeps, _ = make_collector(pages, settings)

    collector.collect(SITE, NAME, lambda _lacking: urls)

    got = [r.url for r in stored]
    assert all(f"https://{OTHER}/x{i}" in got for i in range(5))
    assert sum(u.startswith(f"https://{HOST}/o") for u in got) == 1


def test_stored_addresses_do_not_take_slots_of_the_cut() -> None:
    settings = CollectionSettings(min_delay_seconds=0, backoff_seconds=0, max_retrieval_urls=3)
    pages, outside = _outside_after_own(0, 3)
    collector, _site, stored, _sleeps, _ = make_collector(pages, settings)
    urls = [SITE] * 3 + outside  # the homepage is already stored by the crawl

    collector.collect(SITE, NAME, lambda _lacking: urls)

    assert [r.url for r in stored if r.url.startswith(f"https://{OTHER}")] == outside


def test_total_retrieval_fetches_stay_within_the_cut() -> None:
    settings = CollectionSettings(min_delay_seconds=0, backoff_seconds=0, max_retrieval_urls=4)
    pages, urls = _outside_after_own(2, 10)
    collector, _site, stored, _sleeps, _ = make_collector(pages, settings)

    collector.collect(SITE, NAME, lambda _lacking: urls)

    assert len(stored) - 1 <= 4  # minus the homepage of the crawl


def test_only_own_domain_or_non_http_addresses_raise_no_error() -> None:
    pages, urls = _outside_after_own(3, 0)
    collector, _site, stored, _sleeps, _ = make_collector(pages)

    collector.collect(SITE, NAME, lambda _lacking: [*urls, "ftp://x.example/a"])

    assert len(stored) == 2  # homepage and one own-domain address
