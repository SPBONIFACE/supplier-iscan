"""#20: the strategy ladder, the failure log, the attempt cap, retrieval addresses, identity flag.

Mock sites only; no network, no real provider.
"""

import json
import re
from pathlib import Path

import httpx2
import pytest

from app.collection.collector import RetrieveFn
from app.collection.failures import MESSAGES, RetrievalFailed
from app.collection.retrieval import rank
from app.collection.settings import CollectionSettings
from app.http_client import FetchTimeoutError
from app.providers import RetrievedUrl
from tests.collection.support import HOST, INTERNAL, OTHER, chunks, html, make_collector
from tests.http_client.support import redirect

NAME = "Acme Supplies SA"
SITE = f"https://{HOST}/"
CASES = Path(__file__).parent / "cases" / "retrieval_cases.json"
NEGATIVE = re.compile(r"\b(does not have|has no|is not certified|lacks|never)\b", re.IGNORECASE)


def content_requests(site) -> list[str]:  # type: ignore[no-untyped-def]
    skipped = ("/robots.txt", "/.well-known/tdmrep.json")
    return [r.url for r in site.seen if not r.url.endswith(skipped)]


def retrieve_of(*urls: str) -> RetrieveFn:
    return lambda _lacking: list(urls)


# -- the failure log ----------------------------------------------------------------------------


def test_each_failure_is_logged_with_url_strategy_kind_and_next_strategy() -> None:
    pages = {
        (HOST, "/"): html("<a href='/about'>About</a><a href='/esg'>ESG</a>"),
        (HOST, "/about"): httpx2.Response(500),
        (HOST, "/esg"): html(""),  # no readable text
    }
    collector, _site, _stored, _sleeps, _ = make_collector(pages)

    result = collector.collect(SITE, NAME)

    by_url = {f.url: f for f in result.failures}
    about = by_url[f"https://{HOST}/about"]
    assert (about.strategy, about.kind, about.next_strategy) == ("website", "http_error", "sitemap")
    assert by_url[f"https://{HOST}/esg"].kind == "empty_content"
    sitemap = by_url[f"https://{HOST}/sitemap.xml"]
    assert (sitemap.strategy, sitemap.kind, sitemap.next_strategy) == (
        "sitemap",
        "http_error",
        "retrieval",
    )
    assert all(f.message for f in result.failures)


def test_a_timeout_and_an_unreachable_page_are_told_apart() -> None:
    collector, site, _stored, _sleeps, _ = make_collector({})

    def fail(request: httpx2.Request) -> None:
        if request.url.path == "/":
            raise FetchTimeoutError("slow")
        if request.url.path == "/sitemap.xml":
            raise httpx2.ConnectError("down")

    site.error = fail
    result = collector.collect(SITE, NAME)

    kinds = {f.url: f.kind for f in result.failures}
    assert kinds[SITE] == "timeout"
    assert kinds[f"https://{HOST}/sitemap.xml"] == "unreachable"


def test_a_page_blocked_by_robots_txt_is_logged() -> None:
    pages = {
        (HOST, "/robots.txt"): httpx2.Response(200, text="User-agent: *\nDisallow: /about\n"),
        (HOST, "/"): html("<a href='/about'>About</a>"),
        (HOST, "/about"): html("<p>Acme</p>"),
    }
    collector, _site, stored, _sleeps, _ = make_collector(pages)

    result = collector.collect(SITE, NAME)

    blocked = [f for f in result.failures if f.kind == "blocked_by_robots"]
    assert [f.url for f in blocked] == [f"https://{HOST}/about"]
    assert len(stored) == 1


def test_crawl_rules_that_could_not_be_read_are_not_logged_as_a_block() -> None:
    """robots.txt did not answer (the Corvaglia run from Cloud Run): the domain is not crawled
    (Q16), and the log says the rules could not be read, not that the site forbids it."""
    pages = {
        (HOST, "/robots.txt"): httpx2.Response(503),
        (HOST, "/"): html("<p>Acme</p>"),
    }
    collector, _site, stored, _sleeps, _ = make_collector(pages)

    result = collector.collect(SITE, NAME)

    kinds = {f.url: f.kind for f in result.failures}
    assert kinds[SITE] == "crawl_rules_unreadable"
    assert "blocked_by_robots" not in kinds.values()
    assert stored == []
    assert "could not be read" in MESSAGES["crawl_rules_unreadable"]


def test_failure_messages_are_plain_and_never_a_negative_claim_about_the_supplier() -> None:
    for kind, message in MESSAGES.items():
        assert not NEGATIVE.search(message), kind
    assert MESSAGES["empty_content"].startswith("No public evidence found")


# -- the attempt cap ----------------------------------------------------------------------------


def test_no_attempt_is_made_beyond_the_cap_across_strategies_and_retrieval_urls() -> None:
    cap = 4
    settings = CollectionSettings(
        min_delay_seconds=0, backoff_seconds=0, retries=1, max_attempts=cap, max_retrieval_urls=5
    )
    pages = {
        (HOST, "/"): httpx2.Response(503),
        (HOST, "/sitemap.xml"): httpx2.Response(503),
        (OTHER, "/a"): html("<p>a</p>"),
    }
    collector, site, stored, _sleeps, _ = make_collector(pages, settings)

    result = collector.collect(SITE, NAME, retrieve_of(*(f"https://{OTHER}/{c}" for c in "abcde")))

    assert result.attempts == cap
    assert len(content_requests(site)) <= cap
    assert not stored  # the home page used 2 attempts, the sitemap 2: nothing is left
    assert [f.kind for f in result.failures].count("attempt_cap") == 1


def test_the_cap_is_shared_by_the_website_and_the_retrieval_urls() -> None:
    settings = CollectionSettings(
        min_delay_seconds=0, backoff_seconds=0, retries=0, max_attempts=3, max_retrieval_urls=5
    )
    pages = {(HOST, "/"): html("<p>Acme Supplies</p>")}
    for c in "abcde":
        pages[(OTHER, f"/{c}")] = html("<p>x</p>")
    collector, site, stored, _sleeps, _ = make_collector(pages, settings)

    collector.collect(SITE, NAME, retrieve_of(*(f"https://{OTHER}/{c}" for c in "abcde")))

    assert len(content_requests(site)) == 3  # home, sitemap, one retrieval address
    assert len(stored) == 2


# -- retrieval addresses are hostile input ------------------------------------------------------


def test_retrieval_urls_are_fetched_and_stored_like_crawled_sources() -> None:
    pages = {
        (HOST, "/"): html("<p>Acme Supplies SA</p>"),
        (OTHER, "/profile"): html("<p>Register entry of Acme Supplies SA</p>"),
    }
    collector, _site, stored, _sleeps, recorded = make_collector(pages)

    result = collector.collect(SITE, NAME, retrieve_of(f"https://{OTHER}/profile"))

    assert [r.url for r in stored] == [SITE, f"https://{OTHER}/profile"]
    assert {p.domain for p in recorded} == {HOST, OTHER}  # the permission check ran for both
    assert result.identity_to_verify is False


def test_hostile_retrieval_urls_are_refused_without_a_request_to_them() -> None:
    pages = {
        (HOST, "/"): html("<p>Acme Supplies SA</p>"),
        (OTHER, "/loop"): redirect(f"https://{OTHER}/loop"),
        (OTHER, "/to-private"): redirect(f"https://{INTERNAL}/secret"),
        (INTERNAL, "/secret"): html("<p>secret</p>"),
    }
    collector, site, stored, _sleeps, _ = make_collector(pages)
    hostile = [
        "http://127.0.0.1/admin",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data",
        f"https://{INTERNAL}/secret",
        "file:///etc/passwd",
        "ftp://registry.example/x",
        f"https://{OTHER}/to-private",
        f"https://{OTHER}/loop",
    ]

    result = collector.collect(SITE, NAME, retrieve_of(*hostile))

    assert [r.url for r in stored] == [SITE]
    seen = [r.connect_host for r in site.seen]
    assert "10.0.0.5" not in seen and "127.0.0.1" not in seen and "169.254.169.254" not in seen
    refused = {f.url for f in result.failures if f.strategy == "retrieval"}
    assert "file:///etc/passwd" in refused and "http://127.0.0.1/admin" in refused


def test_a_huge_retrieval_file_is_not_read_beyond_the_limit() -> None:
    seen: list[int] = []
    huge = httpx2.Response(200, content=chunks(50_000_000, 1_000_000, seen))
    huge.headers["content-type"] = "application/pdf"
    settings = CollectionSettings(min_delay_seconds=0, backoff_seconds=0, max_pdf_bytes=100_000)
    pages = {(HOST, "/"): html("<p>Acme Supplies SA</p>"), (OTHER, "/big.pdf"): huge}
    collector, _site, stored, _sleeps, _ = make_collector(pages, settings)

    result = collector.collect(SITE, NAME, retrieve_of(f"https://{OTHER}/big.pdf"))

    assert [r.url for r in stored] == [SITE]
    assert sum(seen) < 5_000_000
    assert "too_large" in {f.kind for f in result.failures}


def test_a_retrieval_failure_is_logged_and_the_other_sources_are_kept() -> None:
    def broken(_lacking: list[str]) -> list[str]:
        raise RetrievalFailed("provider_unavailable")

    collector, _site, stored, _sleeps, _ = make_collector(
        {(HOST, "/"): html("<p>Acme Supplies</p>")}
    )

    result = collector.collect(SITE, NAME, broken)

    assert len(stored) == 1
    (failure,) = [f for f in result.failures if f.strategy == "retrieval"]
    assert (failure.kind, failure.url, failure.next_strategy) == (
        "provider_unavailable",
        None,
        None,
    )


# -- identity_to_verify (owner decision D-065) -------------------------------------------------


def test_a_run_that_finds_nothing_at_all_is_not_flagged() -> None:
    collector, _site, stored, _sleeps, _ = make_collector({})

    result = collector.collect(SITE, NAME, retrieve_of())

    assert not stored and result.identity_to_verify is False


def test_no_website_source_but_other_sources_is_flagged() -> None:
    pages = {(OTHER, "/profile"): html("<p>Acme Supplies SA is listed here.</p>")}
    collector, _site, stored, _sleeps, _ = make_collector(pages)

    result = collector.collect(SITE, NAME, retrieve_of(f"https://{OTHER}/profile"))

    assert len(stored) == 1 and result.identity_to_verify is True


def test_an_identity_without_a_website_and_a_retrieved_source_is_flagged() -> None:
    pages = {(OTHER, "/profile"): html("<p>Acme Supplies SA</p>")}
    collector, _site, stored, _sleeps, _ = make_collector(pages)

    result = collector.collect(None, NAME, retrieve_of(f"https://{OTHER}/profile"))

    assert len(stored) == 1 and result.identity_to_verify is True


def test_retrieved_text_does_not_clear_a_website_that_lacks_the_name() -> None:
    pages = {
        (HOST, "/"): html("<p>Welcome to Acme Supplies.</p>"),
        (OTHER, "/profile"): html("<p>Acme Supplies SA</p>"),
    }
    collector, _site, _stored, _sleeps, _ = make_collector(pages)
    assert (
        collector.collect(SITE, NAME, retrieve_of(f"https://{OTHER}/profile")).identity_to_verify
        is False
    )

    other_pages = {
        (HOST, "/"): html("<p>A family business.</p>"),
        (OTHER, "/profile"): html("<p>Acme Supplies SA</p>"),
    }
    collector, _site, _stored, _sleeps, _ = make_collector(other_pages)
    result = collector.collect(SITE, NAME, retrieve_of(f"https://{OTHER}/profile"))
    assert result.identity_to_verify is True  # only the website's own content is compared


# -- retrieval cases (data for the #22 harness; plumbing only) ----------------------------------


def test_the_retrieval_cases_load_and_run_through_the_plumbing() -> None:
    """These cases prove plumbing only (ranking, fetch, store). They do not measure retrieval
    quality: that is the #22 evaluation, on a real provider."""
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    assert cases
    for case in cases:
        pages = {(HOST, "/"): html("<p>Home</p>")}
        for url, body in case["pages"].items():
            host, path = url.removeprefix("https://").split("/", 1)
            pages[(host, "/" + path)] = html(body)
        offered = [RetrievedUrl(**item) for item in case["provider_urls"]]
        ranked = rank(offered, case["lacking"])
        assert ranked[0] == case["expect_first"], case["id"]
        collector, _site, stored, _sleeps, _ = make_collector(pages)

        collector.collect(SITE, case["legal_name"], retrieve_of(*ranked))

        assert {r.url for r in stored} - {SITE} == set(case["expect_stored"]), case["id"]
        for record in stored:  # the snippets are never stored
            assert all(item.snippet not in record.text for item in offered if item.snippet)


@pytest.mark.parametrize("snippet", ["ISO 9001 certificate", "our sustainability report"])
def test_a_snippet_only_ranks(snippet: str) -> None:
    offered = [
        RetrievedUrl(url="https://a.example/x", snippet="unrelated"),
        RetrievedUrl(url="https://b.example/y", snippet=snippet),
    ]

    assert rank(offered, ["certifications", "sustainability"])[0] == "https://b.example/y"
