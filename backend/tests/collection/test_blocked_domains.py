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
NEVER = "linkedin.com"  # the shipped never-contact default (#186)
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
    assert asked == [tuple(sorted((HOST, NEVER)))]  # the provider is told to leave the domain out
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

    assert asked == [(NEVER,), tuple(sorted((DIRECTORY, NEVER)))]
    assert f"https://{PRESS}/1" in [r.url for r in stored]


def test_no_second_request_when_no_domain_closed() -> None:
    pages = {(HOST, "/"): html("<p>Acme Supplies SA</p>"), (OTHER, "/r"): html("<p>Acme</p>")}
    collector, _site, _stored, _sleeps, _ = make_collector(pages)
    asked: list[tuple[str, ...]] = []

    def retrieve(_lacking: list[str], excluded: tuple[str, ...]) -> list[str]:
        asked.append(excluded)
        return [f"https://{OTHER}/r"]

    collector.collect(SITE, NAME, retrieve)

    assert asked == [(NEVER,)]


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


# --- #186: domains whose terms forbid automated collection are never contacted ---------------

LINKEDIN = "www.linkedin.com"


def _never_settings(**kw: object) -> CollectionSettings:
    return CollectionSettings(min_delay_seconds=0, backoff_seconds=0, **kw)  # type: ignore[arg-type]


def test_the_provider_is_told_to_exclude_linkedin_from_the_first_request() -> None:
    collector, _site, _stored, _sleeps, _ = make_collector({(HOST, "/"): html("<p>Acme</p>")})
    asked: list[tuple[str, ...]] = []

    def retrieve(_lacking: list[str], excluded: tuple[str, ...]) -> list[str]:
        asked.append(excluded)
        return []

    collector.collect(SITE, NAME, retrieve)

    assert asked and "linkedin.com" in asked[0]


@pytest.mark.parametrize("host", ["www.linkedin.com", "fr.linkedin.com", "linkedin.com"])
def test_a_returned_linkedin_address_is_not_requested_and_logged_once(host: str) -> None:
    pages = {(HOST, "/"): html("<p>Acme Supplies SA</p>"), (PRESS, "/1"): html("<p>Acme press</p>")}
    collector, site, stored, _sleeps, _ = make_collector(pages)
    urls = [f"https://{host}/company/acme", f"https://{host}/in/someone", f"https://{PRESS}/1"]

    result = collector.collect(SITE, NAME, lambda _l, _e: urls)

    assert not [h for h, _p in _requested(site) if h.endswith("linkedin.com")]
    rows = [f for f in result.failures if f.kind == "not_contacted"]
    assert [f.url for f in rows] == [f"https://{host}/company/acme"]
    assert "terms do not allow automated collection" in rows[0].message
    assert [r.url for r in stored if "linkedin" in r.url] == []
    assert f"https://{PRESS}/1" in [r.url for r in stored]


def test_a_linkedin_address_takes_no_retrieval_slot() -> None:
    pages = {(HOST, "/"): html("<p>Acme</p>"), (PRESS, "/1"): html("<p>Acme press</p>")}
    collector, _site, stored, _sleeps, _ = make_collector(
        pages, _never_settings(max_retrieval_urls=1)
    )
    urls = [f"https://{LINKEDIN}/company/acme", f"https://{PRESS}/1"]

    collector.collect(SITE, NAME, lambda _l, _e: urls)

    assert f"https://{PRESS}/1" in [r.url for r in stored]


def test_a_buyer_website_on_a_never_contact_domain_is_not_requested() -> None:
    collector, site, stored, _sleeps, _ = make_collector({})

    result = collector.collect(f"https://{LINKEDIN}/company/acme", NAME, None)

    assert site.seen == []
    assert [f.kind for f in result.failures] == ["not_contacted"]
    assert stored == []


def test_a_notlinkedin_domain_is_not_matched() -> None:
    other = "notlinkedin.com"
    RESOLVER.answers[other] = [PUBLIC_V4]
    pages = {(HOST, "/"): html("<p>Acme</p>"), (other, "/1"): html("<p>Acme page</p>")}
    collector, _site, stored, _sleeps, _ = make_collector(pages)

    result = collector.collect(SITE, NAME, lambda _l, _e: [f"https://{other}/1"])

    assert not [f for f in result.failures if f.kind == "not_contacted"]
    assert f"https://{other}/1" in [r.url for r in stored]


def test_an_empty_setting_lists_no_domain() -> None:
    from app.collection.settings import load_collection_settings

    assert load_collection_settings({"COLLECT_NEVER_CONTACT_HOSTS": ""}).never_contact_hosts == ()
    assert load_collection_settings({}).never_contact_hosts == ("linkedin.com",)
    RESOLVER.answers[LINKEDIN] = [PUBLIC_V4]
    pages = {(HOST, "/"): html("<p>Acme</p>"), (LINKEDIN, "/company/acme"): html("<p>Acme</p>")}
    collector, _site, stored, _sleeps, _ = make_collector(
        pages, _never_settings(never_contact_hosts=())
    )
    asked: list[tuple[str, ...]] = []

    def retrieve(_lacking: list[str], excluded: tuple[str, ...]) -> list[str]:
        asked.append(excluded)
        return [f"https://{LINKEDIN}/company/acme"]

    result = collector.collect(SITE, NAME, retrieve)

    assert asked[0] == ()
    assert not [f for f in result.failures if f.kind == "not_contacted"]
    assert f"https://{LINKEDIN}/company/acme" in [r.url for r in stored]


def _no_linkedin_request(site) -> None:  # type: ignore[no-untyped-def]
    assert not [(h, p) for h, p in _requested(site) if h.endswith("linkedin.com")]


def test_a_redirect_to_a_never_contact_domain_is_not_followed() -> None:
    pages = {
        (HOST, "/"): html("<p>Acme Supplies SA</p>"),
        (PRESS, "/moved"): httpx2.Response(
            302, headers={"location": f"https://{LINKEDIN}/company/acme"}
        ),
        (PRESS, "/moved2"): httpx2.Response(
            301, headers={"location": f"https://{LINKEDIN}/company/other"}
        ),
        (PRESS, "/ok"): html("<p>Acme press</p>"),
    }
    collector, site, stored, _sleeps, _ = make_collector(pages)
    urls = [f"https://{PRESS}/moved", f"https://{PRESS}/moved2", f"https://{PRESS}/ok"]

    result = collector.collect(SITE, NAME, lambda _l, _e: urls)

    _no_linkedin_request(site)  # no robots.txt, no tdmrep.json, no page
    rows = [f for f in result.failures if f.kind == "not_contacted"]
    assert [f.url for f in rows] == [f"https://{LINKEDIN}/company/acme"]  # once per domain
    assert f"https://{PRESS}/ok" in [r.url for r in stored]


def test_a_page_link_and_a_sitemap_entry_on_a_never_contact_domain_are_not_requested() -> None:
    home = (
        f"<p>Acme Supplies SA</p><a href='https://{LINKEDIN}/company/acme/report.pdf'>Report</a>"
        f"<a href='https://{LINKEDIN}/company/acme'>Follow us</a>"
    )
    sitemap = (
        "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
        f"<url><loc>https://{LINKEDIN}/company/acme/about</loc></url></urlset>"
    )
    pages = {
        (HOST, "/"): html(home),
        (HOST, "/sitemap.xml"): httpx2.Response(
            200, text=sitemap, headers={"content-type": "application/xml"}
        ),
    }
    collector, site, _stored, _sleeps, _ = make_collector(pages)

    result = collector.collect(SITE, NAME, None)

    _no_linkedin_request(site)
    rows = [f for f in result.failures if f.kind == "not_contacted"]
    assert len(rows) <= 1  # one per domain per run


def test_never_contact_addresses_consume_no_ceiling() -> None:
    pages = {(HOST, "/"): html("<p>Acme</p>"), (PRESS, "/1"): html("<p>Acme press</p>")}
    limits = _never_settings(max_attempts=3, max_retrieval_urls=1, max_domains=2)
    with_linkedin, site, stored, _s, _ = make_collector(pages, limits)
    noise = [f"https://{LINKEDIN}/{i}" for i in range(20)]
    result = with_linkedin.collect(SITE, NAME, lambda _l, _e: [*noise, f"https://{PRESS}/1"])
    baseline, _site2, _stored2, _s2, _ = make_collector(pages, limits)
    expected = baseline.collect(SITE, NAME, lambda _l, _e: [f"https://{PRESS}/1"])

    _no_linkedin_request(site)
    assert result.attempts == expected.attempts  # attempts
    assert not [f for f in result.failures if f.kind == "attempt_cap"]  # attempt, domain caps
    assert f"https://{PRESS}/1" in [r.url for r in stored]  # the single retrieval slot
    assert len(site.seen) == len(_site2.seen)  # requests: the same as without the addresses
