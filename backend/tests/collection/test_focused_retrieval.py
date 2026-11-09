"""#141: focused retrieval requests and a reserved budget for independent sources."""

from types import SimpleNamespace
from typing import Any

import pytest

from app.collection.collector import RetrievedAddresses
from app.collection.failures import RetrievalFailed
from app.collection.retrieval import IdentityRecord, make_retriever
from app.collection.settings import FOCUSES, CollectionSettings, load_collection_settings
from app.collection.source_store import IdentityRedaction
from app.config import ConfigurationError
from app.prompts import load_prompt_set
from app.providers import ProviderCallError, RetrievedUrl
from app.redaction.text import mint
from tests.collection.support import HOST, OTHER, html, make_collector

NAME = "Acme Supplies SA"
SITE = f"https://{HOST}/"
IDENTITY = IdentityRecord(NAME, SITE, "DE")


class FakeGate:
    def redact(self, text: str, **_kw: Any) -> Any:
        return mint(text)


class FakeClient:
    def __init__(self, answers: dict[str, list[str] | Exception]) -> None:
        self.answers = answers
        self.queries: list[str] = []

    def retrieve(self, request: Any, _context: Any) -> Any:
        self.queries.append(request.query.text)
        for focus, answer in self.answers.items():
            if focus and f"Focus: {focus}" in request.query.text:
                if isinstance(answer, Exception):
                    raise answer
                return SimpleNamespace(urls=[RetrievedUrl(url=u) for u in answer])
        fallback = self.answers.get("")
        if isinstance(fallback, Exception):
            raise fallback
        return SimpleNamespace(urls=[RetrievedUrl(url=u) for u in fallback or []])


def retriever(client: FakeClient, focuses: tuple[str, ...]) -> Any:
    providers = SimpleNamespace(retrieval=lambda: client)
    return make_retriever(
        providers,  # type: ignore[arg-type]
        load_prompt_set(),
        FakeGate(),  # type: ignore[arg-type]
        IdentityRedaction(),
        IDENTITY,
        None,  # type: ignore[arg-type]
        focuses,
    )


ANSWERS: dict[str, list[str] | Exception] = {
    "official registers": ["https://r.example/1", "https://r.example/2", "https://dup.example/"],
    "certification bodies": ["https://c.example/1", "https://dup.example/"],
    "news and trade": ["https://n.example/1"],
    "pages naming": ["https://u.example/1", "https://u.example/2"],
}


def test_four_focuses_four_requests_in_order_merged_round_robin_without_duplicates() -> None:
    client = FakeClient(dict(ANSWERS))

    urls = retriever(client, FOCUSES)([])

    assert len(client.queries) == 4
    for query, word in zip(
        client.queries,
        ("official registers", "certification bodies", "news and trade", "pages naming"),
        strict=True,
    ):
        assert f"Focus: {word}" in query
    assert list(urls) == [
        "https://r.example/1",
        "https://c.example/1",
        "https://n.example/1",
        "https://u.example/1",
        "https://r.example/2",
        "https://dup.example/",
        "https://u.example/2",
    ]


def test_one_focus_failing_is_reported_and_the_others_are_still_fetched() -> None:
    answers = dict(ANSWERS)
    answers["certification bodies"] = ProviderCallError(provider="p", config_id="c", kind="timeout")
    client = FakeClient(answers)

    urls = retriever(client, FOCUSES)(["about"])

    assert len(client.queries) == 4
    assert isinstance(urls, RetrievedAddresses)
    assert [f.kind for f in urls.failures] == ["provider_unavailable"]
    assert "https://c.example/1" not in urls and "https://n.example/1" in urls


def test_the_collector_records_a_failed_focus_and_fetches_the_rest() -> None:
    pages = {(OTHER, "/x"): html("<p>x</p>")}
    collector, _site, _stored, _s, _ = make_collector(pages)
    partial = RetrievedAddresses([f"https://{OTHER}/x"])
    partial.failures = [RetrievalFailed("provider_unavailable")]

    result = collector.collect(None, NAME, lambda _lacking: partial)

    assert [f.kind for f in result.failures if f.strategy == "retrieval"] == [
        "provider_unavailable"
    ]
    assert len(result.sources) == 1


def test_all_focuses_failing_gives_no_address_and_one_failure_per_focus() -> None:
    client = FakeClient({"": ProviderCallError(provider="p", config_id="c", kind="timeout")})

    urls = retriever(client, FOCUSES[:2])([])

    assert isinstance(urls, RetrievedAddresses) and list(urls) == []
    assert len(urls.failures) == 2


def test_no_focus_keeps_a_single_request_without_focus_line() -> None:
    client = FakeClient({"": ["https://r.example/1"]})

    urls = retriever(client, ())([])

    assert len(client.queries) == 1 and "Focus:" not in client.queries[0]
    assert urls == ["https://r.example/1"]


def test_the_crawl_stops_at_max_pages_minus_the_reserved_slots() -> None:
    pages = {
        (HOST, "/"): html(
            "<p>Acme Supplies SA</p><a href='/about'>About</a><a href='/sustainability'>S</a>"
            "<a href='/quality'>Q</a><a href='/locations'>L</a>"
        )
    }
    for path in ("about", "sustainability", "quality", "locations"):
        pages[(HOST, f"/{path}")] = html(f"<p>{path}</p>")
    settings = CollectionSettings(
        max_pages=3, reserved_independent=1, min_delay_seconds=0, backoff_seconds=0
    )
    collector, _site, stored, _s, _ = make_collector(pages, settings)

    collector.collect(SITE, NAME)

    assert len(stored) == 2  # the home page plus one: 3 - 1 reserved


def test_the_crawl_keeps_at_least_one_page() -> None:
    assert CollectionSettings(max_pages=4, reserved_independent=9).crawl_pages == 1


def test_reserved_slots_are_not_given_to_an_own_domain_address() -> None:
    pages = {
        (HOST, "/"): html("<p>Acme Supplies SA</p>"),
        (HOST, "/a"): html("<p>own a</p>"),
        (OTHER, "/x"): html("<p>other x</p>"),
    }
    settings = CollectionSettings(
        max_pages=2, reserved_independent=1, min_delay_seconds=0, backoff_seconds=0
    )
    collector, _site, stored, _s, _ = make_collector(pages, settings)

    result = collector.collect(SITE, NAME, lambda _l: [f"https://{HOST}/a", f"https://{OTHER}/x"])

    assert [r.url for r in stored] == [SITE, f"https://{OTHER}/x"]
    assert f"https://{HOST}/a" in result.skipped


def test_an_own_domain_address_beyond_the_first_is_still_dropped() -> None:
    pages = {
        (HOST, "/"): html("<p>Acme Supplies SA</p>"),
        (HOST, "/a"): html("<p>a</p>"),
        (HOST, "/b"): html("<p>b</p>"),
        (OTHER, "/x"): html("<p>x</p>"),
    }
    collector, _site, stored, _s, _ = make_collector(pages)
    urls = [f"https://{HOST}/a", f"https://{HOST}/b", f"https://{OTHER}/x"]

    collector.collect(SITE, NAME, lambda _l: urls)

    assert [r.url for r in stored] == [SITE, f"https://{HOST}/a", f"https://{OTHER}/x"]


def test_settings_defaults_and_environment() -> None:
    d = load_collection_settings({})
    assert d.reserved_independent == 6 and d.retrieval_focuses == FOCUSES
    custom = load_collection_settings(
        {"COLLECT_RETRIEVAL_FOCUSES": "news, registers", "COLLECT_RESERVED_INDEPENDENT": "2"}
    )
    assert custom.retrieval_focuses == ("news", "registers") and custom.reserved_independent == 2
    assert load_collection_settings({"COLLECT_RETRIEVAL_FOCUSES": ""}).retrieval_focuses == ()
    with pytest.raises(ConfigurationError):
        load_collection_settings({"COLLECT_RETRIEVAL_FOCUSES": "bogus"})
