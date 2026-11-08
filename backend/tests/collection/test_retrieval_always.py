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


def test_the_default_number_of_retrieval_addresses_is_eight() -> None:
    assert CollectionSettings().max_retrieval_urls == 8


def test_a_failing_retrieval_with_nothing_lacking_keeps_the_website_sources() -> None:
    def broken(_lacking: list[str]) -> list[str]:
        raise RetrievalFailed("provider_unavailable")

    collector, _site, stored, _sleeps, _ = make_collector(full_site())

    result = collector.collect(SITE, NAME, broken)

    assert len(stored) == 5
    assert [f.kind for f in result.failures if f.strategy == "retrieval"] == [
        "provider_unavailable"
    ]
