"""#182: addresses ranked by substance, low-value hosts last, refused sites take no source slot.

The recorded case is the Corvaglia run on dev (14 Nov 2026): the supplier's website answered with a
bot check, six third-party sites refused or blocked us, two directory pages and four substantive
pages were returned, and the attempt cap cut the substantive ones.
"""

import httpx2
import pytest

from app.collection.budget import RequestBudget
from app.collection.collector import Collector
from app.collection.retrieval import IdentityRecord, _supplier_text, rank, significant_word
from app.collection.settings import (
    LOW_VALUE_HOSTS,
    CollectionSettings,
    load_collection_settings,
)
from app.collection.source_store import SourceRecord
from app.crawl import EmptySuppressionList, PermittedFetcher, build_client
from app.providers import RetrievedUrl
from tests.collection.support import CONTACT, HOST, RESOLVER, html, make_collector
from tests.http_client.support import PUBLIC_V4, MockSite

NAME = "Corvaglia Holding AG"
SITE = f"https://{HOST}/"
CHALLENGE = httpx2.Response(403, text="<html><div class='cf-turnstile'></div></html>")
REFUSING = [f"refuses{i}.example" for i in range(6)]
DIRECTORIES = ["www.yellowpages.swiss", "de.kompass.com"]
SUBSTANTIVE = ["packaging-gateway.com", "sqs.ch", "tradepress.example", "register.example"]


@pytest.fixture(autouse=True)
def _hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    for host in (*REFUSING, *DIRECTORIES, *SUBSTANTIVE):
        monkeypatch.setitem(RESOLVER.answers, host, [PUBLIC_V4])


def _item(url: str, snippet: str = "") -> RetrievedUrl:
    return RetrievedUrl(url=url, snippet=snippet)


def _hosts_of(urls: list[str]) -> list[str]:
    return [u.split("/")[2] for u in urls]


# --- ranking --------------------------------------------------------------------------------


def test_an_address_naming_the_supplier_ranks_before_one_that_does_not() -> None:
    urls = [
        _item("https://a.example/1", "Packaging news of the week"),
        _item("https://b.example/2", "CORVAGLIA opens a plant"),
    ]
    assert rank(urls, [], NAME) == ["https://b.example/2", "https://a.example/1"]


def test_the_match_ignores_case_and_accents() -> None:
    urls = [_item("https://a.example/1", "nothing"), _item("https://b.example/2", "Corvaglía")]
    assert rank(urls, [], "CÓRVAGLIA SA")[0] == "https://b.example/2"


def test_a_low_value_host_ranks_last_inside_each_group() -> None:
    urls = [
        _item("https://www.yellowpages.swiss/c", "Corvaglia"),
        _item("https://press.example/c", "Corvaglia"),
        _item("https://de.kompass.com/c", "other"),
        _item("https://other.example/c", "other"),
    ]
    assert _hosts_of(rank(urls, [], NAME)) == [
        "press.example",
        "www.yellowpages.swiss",
        "other.example",
        "de.kompass.com",
    ]


def test_a_directory_is_ranked_last_never_dropped() -> None:
    urls = [_item("https://cylex.ch/x", "Corvaglia"), _item("https://a.example/", "")]
    assert len(rank(urls, [], NAME)) == 2


def test_the_lacking_page_kind_stays_the_first_key() -> None:
    urls = [
        _item("https://press.example/news", "Corvaglia"),
        _item("https://www.yellowpages.swiss/sustainability", "directory"),
    ]
    assert rank(urls, ["sustainability"], NAME)[0] == "https://www.yellowpages.swiss/sustainability"


def test_a_host_matches_by_suffix_only_on_a_dot_boundary() -> None:
    urls = [_item("https://notkompass.com/x"), _item("https://de.kompass.com/x")]
    assert rank(urls, [], NAME, ("kompass.com",)) == [
        "https://notkompass.com/x",
        "https://de.kompass.com/x",
    ]


def test_a_name_without_a_significant_word_keeps_the_existing_order() -> None:
    urls = [_item("https://a.example/1", "x"), _item("https://b.example/2", "AG")]
    assert significant_word("AG & Co.") == ""
    assert rank(urls, [], "AG & Co.") == ["https://a.example/1", "https://b.example/2"]


def test_an_empty_low_value_list_disables_the_rule() -> None:
    urls = [_item("https://www.yellowpages.swiss/c"), _item("https://a.example/c")]
    assert rank(urls, [], NAME, ()) == ["https://www.yellowpages.swiss/c", "https://a.example/c"]


def test_a_supplier_whose_name_is_a_directory_host_suffix_does_not_crash() -> None:
    urls = [_item("https://other.example/1", "x"), _item("https://kompass.com/2", "Kompass news")]
    assert rank(urls, [], "Kompass SA")[0] == "https://kompass.com/2"  # named, then low-value
    assert len(rank(urls, [], "Kompass SA", ("kompass.com",))) == 2


def test_the_query_keeps_the_quoted_legal_name() -> None:
    text = _supplier_text(IdentityRecord(NAME, None, None), [])
    assert text.splitlines()[0] == f'Legal name: "{NAME}"'


# --- settings -------------------------------------------------------------------------------


def test_the_settings_defaults_and_environment() -> None:
    defaults = load_collection_settings({})
    assert defaults.max_domains == 25 and defaults.max_requests == 200
    assert defaults.low_value_hosts == LOW_VALUE_HOSTS
    assert "yellowpages.swiss" in LOW_VALUE_HOSTS and "kompass.com" in LOW_VALUE_HOSTS
    assert load_collection_settings({"COLLECT_LOW_VALUE_HOSTS": ""}).low_value_hosts == ()
    custom = load_collection_settings({"COLLECT_LOW_VALUE_HOSTS": " A.example, .b.example ,"})
    assert custom.low_value_hosts == ("a.example", "b.example")


# --- refused sites take no slot -------------------------------------------------------------


def test_the_recorded_corvaglia_case_stores_the_substantive_pages_first() -> None:
    pages: dict[tuple[str, str], httpx2.Response] = {(HOST, "/"): CHALLENGE}
    for host in REFUSING:
        pages[(host, "/p")] = CHALLENGE
    for host in DIRECTORIES:
        pages[(host, "/p")] = html("<p>Corvaglia directory entry</p>")
    for host in SUBSTANTIVE:
        pages[(host, "/p")] = html(f"<p>Corvaglia article on {host}</p>")
    # In the order of the log: refusers, directories, then the substantive pages.
    returned = [
        _item(f"https://{h}/p", "Corvaglia" if h not in DIRECTORIES else "Corvaglia listing")
        for h in (*REFUSING, *DIRECTORIES, *SUBSTANTIVE)
    ]
    # Exactly six addresses may be read: 4 + 2, whatever the six refusers did.
    settings = CollectionSettings(min_delay_seconds=0, backoff_seconds=0, max_retrieval_urls=0)
    collector, _site, stored, _sleeps, _ = make_collector(pages, settings)

    result = collector.collect(SITE, NAME, lambda lacking, _e: rank(returned, lacking, NAME))

    urls = [r.url for r in stored]
    assert _hosts_of(urls[:4]) == [*SUBSTANTIVE] or sorted(_hosts_of(urls[:4])) == sorted(
        SUBSTANTIVE
    )
    assert sorted(_hosts_of(urls[4:])) == sorted(DIRECTORIES)
    refused = [f for f in result.failures if f.kind == "bot_check"]
    assert sorted(f.url or "" for f in refused) == sorted(
        [SITE, *(f"https://{h}/p" for h in REFUSING)]
    )
    assert not any(f.kind == "attempt_cap" for f in result.failures)


def test_a_refused_address_does_not_count_but_a_read_one_does() -> None:
    pages = {
        (HOST, "/"): html("<p>Corvaglia Holding AG</p>"),
        ("refuses0.example", "/p"): CHALLENGE,
        ("sqs.ch", "/a"): html("<p>a</p>"),
        ("sqs.ch", "/b"): html("<p>b</p>"),
        ("sqs.ch", "/c"): html("<p>c</p>"),
    }
    settings = CollectionSettings(min_delay_seconds=0, backoff_seconds=0, max_retrieval_urls=2)
    collector, _site, stored, _sleeps, _ = make_collector(pages, settings)
    urls = [
        "https://refuses0.example/p",
        "https://sqs.ch/a",
        "https://sqs.ch/b",
        "https://sqs.ch/c",
    ]

    collector.collect(SITE, NAME, lambda _l, _e: urls)

    assert [r.url for r in stored if "sqs.ch" in r.url] == ["https://sqs.ch/a", "https://sqs.ch/b"]


def test_more_than_the_website_cap_logs_the_cap_row_once(monkeypatch: pytest.MonkeyPatch) -> None:
    hosts = [f"many{i}.example" for i in range(6)]
    for host in hosts:
        monkeypatch.setitem(RESOLVER.answers, host, [PUBLIC_V4])
    pages = {(h, "/p"): html("<p>Corvaglia</p>") for h in hosts}
    pages[(HOST, "/")] = html("<p>Corvaglia Holding AG</p>")
    settings = CollectionSettings(
        min_delay_seconds=0, backoff_seconds=0, max_domains=3, max_retrieval_urls=10, retries=0
    )
    site = MockSite(pages)
    client = build_client(
        CONTACT,
        resolver=RESOLVER,
        inner_transport=site.transport,
        before_request=RequestBudget(settings.max_requests, settings.max_domains),
    )
    stored: list[SourceRecord] = []
    collector = Collector(
        PermittedFetcher(client, EmptySuppressionList(), lambda _p: None),
        settings,
        stored.append,
        sleep=lambda _s: None,
    )

    result = collector.collect(SITE, NAME, lambda _l, _e: [f"https://{h}/p" for h in hosts])

    capped = [f for f in result.failures if "limit of websites" in f.message]
    assert len(capped) == 1
    assert len(stored) == 3  # the website and two more domains
