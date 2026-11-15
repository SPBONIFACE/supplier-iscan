"""#185: no address holds the collection beyond its time limit, the permission checks of the
domain it reaches included."""

import time

import httpx2
import pytest

from app.crawl import EmptySuppressionList, PermittedFetcher, build_client
from app.http_client import FetchSettings, FetchTimeoutError
from tests.http_client.support import PUBLIC_V4, MockSite, StubResolver

HOST = "slow.example"
RESOLVER = StubResolver({HOST: [PUBLIC_V4]})
STEP = 0.35  # seconds the slow site takes for each request


def slow_site() -> MockSite:
    site = MockSite(
        {
            (HOST, "/robots.txt"): httpx2.Response(404),
            (HOST, "/.well-known/tdmrep.json"): httpx2.Response(404),
            (HOST, "/news/a"): httpx2.Response(200, text="<p>news</p>"),
        }
    )
    site.error = lambda _request: time.sleep(STEP)
    return site


def fetcher_for(site: MockSite, timeout: float) -> PermittedFetcher:
    client = build_client(
        "https://iscan.example/contact",
        FetchSettings(timeout_seconds=timeout),
        resolver=RESOLVER,
        inner_transport=site.transport,
    )
    return PermittedFetcher(client, EmptySuppressionList(), lambda _permission: None)


def test_the_permission_checks_and_the_page_of_a_new_domain_are_cut_at_the_fetch_timeout() -> None:
    """A slow site answers robots.txt and tdmrep.json in 0.35 s each (timeout 0.3 s): the page is
    refused before it is sent, so that one address never holds the collection for more than its
    timeout plus the checks of its domain (the collector then retries it and gives up)."""
    site = slow_site()
    fetcher = fetcher_for(site, timeout=0.3)

    started = time.monotonic()
    with pytest.raises(FetchTimeoutError):  # the collector retries it, then gives up
        fetcher.fetch(f"https://{HOST}/news/a")
    elapsed = time.monotonic() - started

    assert [request.host_header for request in site.seen] == [HOST, HOST]  # robots and tdmrep
    assert elapsed < 1.0
