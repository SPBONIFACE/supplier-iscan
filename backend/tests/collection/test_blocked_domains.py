"""#181: a domain that blocks us or does not answer is closed for the rest of the run.

The recorded case is the Corvaglia run on dev (14 Nov 2026): the supplier's website answered the
crawler with a bot check; the website crawl, both sitemaps and ten retrieval addresses on the same
domain were each tried and logged, and only two third-party pages were left in the slots.
"""

import httpx2
import pytest

from app.collection.retrieval import (
    EXCLUDED_LINE,
    OWN_SITE_UNREADABLE_REQUEST,
    IdentityRecord,
    _supplier_text,
)
from app.collection.settings import CollectionSettings
from app.http_client import FetchTimeoutError
from tests.collection.support import HOST, OTHER, RESOLVER, html, make_collector
from tests.http_client.support import PUBLIC_V4

NAME = "Acme Supplies SA"
SITE = f"https://{HOST}/"
PRESS = "press.example"
DIRECTORY = "directory.example"
ROBOTS = f"User-agent: *\nDisallow: /wp-admin/\nSitemap: https://{HOST}/sitemap_index.xml\n"
CHALLENGE = httpx2.Response(403, text="<html><div class='cf-turnstile'></div></html>")


def _requested(site) -> list[tuple[str, str]]:  # type: ignore[no-untyped-def]
    """(host, path without the leading slash) of every request: the mock site records the
    connected address, not the host name."""
    return [(r.host_header, r.url.split("/", 3)[-1]) for r in site.seen]


@pytest.fixture(autouse=True)
def _more_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    for host in (PRESS, DIRECTORY):
        monkeypatch.setitem(RESOLVER.answers, host, [PUBLIC_V4])


def test_a_website_that_answers_with_a_bot_check_is_logged_once_and_left_out() -> None:
    own = [f"https://{HOST}/company/", f"https://www.{HOST}/contact/", f"https://{HOST}/iso.pdf"]
    third = [f"https://{PRESS}/a{i}" for i in range(8)]
    pages = {
        (HOST, "/robots.txt"): httpx2.Response(200, text=ROBOTS),
        (HOST, "/"): CHALLENGE,
        **{(PRESS, f"/a{i}"): html(f"<p>Acme Supplies SA news {i}</p>") for i in range(8)},
    }
    settings = CollectionSettings(min_delay_seconds=0, backoff_seconds=0, max_retrieval_urls=4)
    collector, site, stored, _sleeps, _ = make_collector(pages, settings)
    asked: list[tuple[str, ...]] = []

    def retrieve(_lacking: list[str], excluded: tuple[str, ...]) -> list[str]:
        asked.append(excluded)
        return [*own, *third]

    result = collector.collect(SITE, NAME, retrieve)

    on_host = [f for f in result.failures if f.url and HOST in f.url]
    assert [(f.url, f.strategy, f.kind) for f in on_host] == [(SITE, "website", "bot_check")]
    on_site = [path for host, path in _requested(site) if host == HOST]
    assert on_site == ["robots.txt", ".well-known/tdmrep.json", ""]  # no sitemap, no other page
    assert asked == [(HOST,)]  # the provider is told to leave the domain out
    # The own-domain addresses took no slot; the website's unused pages went to third parties:
    # 4 retrieval slots + crawl_pages (6) = 8 third-party pages.
    assert [r.url for r in stored] == third


def test_crawl_rules_that_could_not_be_read_close_the_domain_with_one_row() -> None:
    pages = {(HOST, "/robots.txt"): httpx2.Response(503), (OTHER, "/r"): html("<p>Acme</p>")}
    collector, _site, stored, _sleeps, _ = make_collector(pages)

    result = collector.collect(
        SITE, NAME, lambda _l, _e: [f"https://{HOST}/about", f"https://{OTHER}/r"]
    )

    kinds = [(f.url, f.kind) for f in result.failures]
    assert kinds == [(SITE, "crawl_rules_unreadable")]
    assert [r.url for r in stored] == [f"https://{OTHER}/r"]


def test_a_third_party_domain_with_a_bot_check_is_tried_once() -> None:
    pages = {
        (HOST, "/"): html("<p>Acme Supplies SA</p>"),
        (DIRECTORY, "/1"): httpx2.Response(403, text="<html>g-recaptcha</html>"),
        (DIRECTORY, "/2"): html("<p>never requested</p>"),
        (PRESS, "/1"): html("<p>Acme Supplies SA in the press</p>"),
    }
    collector, site, stored, _sleeps, _ = make_collector(pages)
    urls = [f"https://{DIRECTORY}/1", f"https://{DIRECTORY}/2", f"https://{PRESS}/1"]

    result = collector.collect(SITE, NAME, lambda _l, _e: urls)

    directory = [f for f in result.failures if f.url and DIRECTORY in f.url]
    assert [(f.url, f.kind) for f in directory] == [(f"https://{DIRECTORY}/1", "bot_check")]
    assert (DIRECTORY, "2") not in _requested(site)
    assert (DIRECTORY, "1") in _requested(site)
    assert f"https://{PRESS}/1" in [r.url for r in stored]


def test_a_domain_closed_during_retrieval_leads_to_one_more_request_without_it() -> None:
    pages = {
        (HOST, "/"): html("<p>Acme Supplies SA</p>"),
        (DIRECTORY, "/1"): CHALLENGE,
        (PRESS, "/1"): html("<p>Acme Supplies SA register entry</p>"),
    }
    collector, _site, stored, _sleeps, _ = make_collector(pages)
    asked: list[tuple[str, ...]] = []

    def retrieve(_lacking: list[str], excluded: tuple[str, ...]) -> list[str]:
        asked.append(excluded)
        return [f"https://{PRESS}/1"] if DIRECTORY in excluded else [f"https://{DIRECTORY}/1"]

    collector.collect(SITE, NAME, retrieve)

    assert asked == [(), (DIRECTORY,)]
    assert f"https://{PRESS}/1" in [r.url for r in stored]


def test_no_second_request_when_no_domain_closed() -> None:
    pages = {(HOST, "/"): html("<p>Acme Supplies SA</p>"), (OTHER, "/r"): html("<p>Acme</p>")}
    collector, _site, _stored, _sleeps, _ = make_collector(pages)
    asked: list[tuple[str, ...]] = []

    def retrieve(_lacking: list[str], excluded: tuple[str, ...]) -> list[str]:
        asked.append(excluded)
        return [f"https://{OTHER}/r"]

    collector.collect(SITE, NAME, retrieve)

    assert asked == [()]


def test_a_page_refused_by_one_robots_rule_does_not_close_the_domain() -> None:
    pages = {
        (HOST, "/robots.txt"): httpx2.Response(200, text="User-agent: *\nDisallow: /about\n"),
        (HOST, "/"): html("<a href='/about'>About</a><a href='/esg'>Sustainability</a>"),
        (HOST, "/about"): html("<p>Acme</p>"),
        (HOST, "/esg"): html("<p>Acme sustainability</p>"),
    }
    collector, site, stored, _sleeps, _ = make_collector(pages)

    result = collector.collect(SITE, NAME)

    assert [f.kind for f in result.failures if f.url == f"https://{HOST}/about"] == [
        "blocked_by_robots"
    ]
    assert f"https://{HOST}/esg" in [r.url for r in stored]
    assert (HOST, "esg") in _requested(site)


def test_the_query_names_the_closed_domains_and_asks_for_third_party_sources() -> None:
    identity = IdentityRecord("Corvaglia", "https://www.corvaglia.example/", "CH")

    text = _supplier_text(identity, ["about"], None, ("corvaglia.example", "directory.example"))

    assert text.splitlines()[0] == 'Legal name: "Corvaglia"'  # still quoted (#179)
    assert OWN_SITE_UNREADABLE_REQUEST in text
    assert "Field groups lacking evidence" not in text
    assert EXCLUDED_LINE.format(domains="corvaglia.example, directory.example") in text


def test_the_query_is_unchanged_when_no_domain_is_closed() -> None:
    identity = IdentityRecord("Corvaglia", "https://www.corvaglia.example/", "CH")

    text = _supplier_text(identity, ["about"])

    assert OWN_SITE_UNREADABLE_REQUEST not in text and "Do not return" not in text
    assert "Field groups lacking evidence: about" in text


def _slow(*paths: str):  # type: ignore[no-untyped-def]
    def fail(request: httpx2.Request) -> None:
        if request.headers["host"] == HOST and request.url.path in paths:
            raise FetchTimeoutError("slow")

    return fail


def test_one_slow_page_does_not_close_the_website() -> None:
    pages = {
        (HOST, "/"): html("<a href='/about'>About</a><a href='/esg'>Sustainability</a>"),
        (HOST, "/esg"): html("<p>Acme sustainability</p>"),
    }
    collector, site, stored, _sleeps, _ = make_collector(pages)
    site.error = _slow("/about")

    result = collector.collect(SITE, NAME)

    assert [f.kind for f in result.failures if f.url == f"https://{HOST}/about"] == ["timeout"]
    assert f"https://{HOST}/esg" in [r.url for r in stored]
    assert (HOST, "esg") in _requested(site)


def test_a_second_slow_page_closes_the_website() -> None:
    pages = {
        (HOST, "/"): html(
            "<a href='/about'>About</a><a href='/esg'>Sustainability</a>"
            "<a href='/quality'>Quality</a>"
        ),
        (HOST, "/quality"): html("<p>Acme quality</p>"),
    }
    collector, site, _stored, _sleeps, _ = make_collector(pages)
    site.error = _slow("/about", "/esg")

    result = collector.collect(SITE, NAME)

    timed_out = [f.url for f in result.failures if f.kind == "timeout"]
    assert len(timed_out) == 2
    assert (HOST, "quality") not in _requested(site)
