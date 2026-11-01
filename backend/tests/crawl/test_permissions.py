"""#17: crawl permissions and crawler identity. Mock transports only; no network."""

import logging

import httpx2
import pytest
from protego import Protego

from app.config import ConfigurationError, load_settings
from app.crawl import (
    AI_CRAWLERS,
    EXCLUSION_MESSAGE,
    EmptySuppressionList,
    PermittedFetcher,
    SuppressionList,
    build_client,
    check_domain,
    crawler_user_agent,
)
from app.crawl.permissions import DomainPermission
from tests.http_client.support import PUBLIC_V4, MockSite, StubResolver

CONTACT = "https://iscan.example/contact"
HOST = "acme.example"
RESOLVER = StubResolver({HOST: [PUBLIC_V4], "other.example": [PUBLIC_V4]})
ROBOTS = (HOST, "/robots.txt")
TDMREP = (HOST, "/.well-known/tdmrep.json")


def text(body: str, status: int = 200, **headers: str) -> httpx2.Response:
    return httpx2.Response(status, text=body, headers=headers)


def tdm(body: str = "") -> httpx2.Response:
    return httpx2.Response(200, text=body, headers={"tdm-reservation": "1"})


class Suppressed:
    def __init__(self, *domains: str) -> None:
        self.domains = domains

    def is_suppressed(self, domain: str) -> bool:
        return domain in self.domains


def setup(
    pages: dict[tuple[str, str], httpx2.Response], suppression: SuppressionList | None = None
) -> tuple[MockSite, PermittedFetcher, list[DomainPermission]]:
    site = MockSite(pages)
    client = build_client(CONTACT, resolver=RESOLVER, inner_transport=site.transport)
    recorded: list[DomainPermission] = []
    fetcher = PermittedFetcher(client, suppression or EmptySuppressionList(), recorded.append)
    return site, fetcher, recorded


def paths(site: MockSite) -> list[str]:
    return [request.url.split(PUBLIC_V4)[1] for request in site.seen]


def test_the_signals_are_checked_recorded_and_pages_fetched_when_allowed() -> None:
    site, fetcher, recorded = setup(
        {ROBOTS: text("User-agent: *\nDisallow: /private\n"), (HOST, "/about"): text("About")}
    )

    result = fetcher.fetch(f"https://{HOST}/about")

    assert result.status == "fetched" and result.response.text == "About"
    assert paths(site) == ["/robots.txt", "/.well-known/tdmrep.json", "/about"]
    (permission,) = recorded
    assert (permission.domain, permission.robots_result, permission.decision) == (
        HOST,
        "found",
        "allowed",
    )
    assert not permission.tdm_reservation and not permission.suppression_hit
    assert permission.checked_at is not None
    fetcher.fetch(f"https://{HOST}/about")
    assert len(recorded) == 1  # checked once per domain


@pytest.mark.parametrize(
    "pages",
    [
        {ROBOTS: tdm()},
        {TDMREP: text('[{"location": "/", "tdm-reservation": 1}]')},
        {TDMREP: text('{"location": "/*", "tdm-reservation": "1"}')},
    ],
    ids=["header", "tdmrep.json", "tdmrep.json object"],
)
def test_a_tdm_reservation_excludes_the_domain_and_no_page_is_requested(
    pages: dict[tuple[str, str], httpx2.Response],
) -> None:
    site, fetcher, recorded = setup({**pages, (HOST, "/about"): text("About")})

    assert fetcher.fetch(f"https://{HOST}/about").status == "excluded"

    assert set(paths(site)) <= {"/robots.txt", "/.well-known/tdmrep.json"}
    assert recorded[0].tdm_reservation and recorded[0].decision == "excluded"


def test_a_tdm_header_on_the_tdmrep_response_counts() -> None:
    site, fetcher, _ = setup({TDMREP: tdm("[]")})
    assert fetcher.fetch(f"https://{HOST}/about").status == "excluded"
    assert "/about" not in paths(site)


def test_a_tdm_reservation_of_zero_does_not_exclude() -> None:
    _, fetcher, _ = setup(
        {TDMREP: text('[{"location": "/", "tdm-reservation": 0}]'), (HOST, "/a"): text("A")}
    )
    assert fetcher.fetch(f"https://{HOST}/a").status == "fetched"


@pytest.mark.parametrize("crawler", AI_CRAWLERS)
def test_a_robots_block_naming_an_ai_crawler_excludes_the_domain(crawler: str) -> None:
    site, fetcher, recorded = setup(
        {ROBOTS: text(f"User-agent: {crawler.lower()}\nDisallow: /\n"), (HOST, "/a"): text("A")}
    )

    assert fetcher.fetch(f"https://{HOST}/a").status == "excluded"

    assert "/a" not in paths(site)
    assert recorded[0].robots_result == "ai_blocked" and recorded[0].decision == "excluded"


def test_a_general_block_or_a_partial_ai_rule_is_not_an_ai_reservation() -> None:
    _, fetcher, recorded = setup(
        {
            ROBOTS: text("User-agent: GPTBot\nDisallow: /private\n\nUser-agent: *\nAllow: /\n"),
            (HOST, "/a"): text("A"),
        }
    )
    assert fetcher.fetch(f"https://{HOST}/a").status == "fetched"
    assert recorded[0].robots_result == "found"


def test_a_path_disallowed_for_the_service_is_never_fetched() -> None:
    robots = "User-agent: SupplierIScan\nDisallow: /secret/*\nAllow: /secret/open$\n"
    site, fetcher, _ = setup(
        {ROBOTS: text(robots), (HOST, "/secret/x"): text("x"), (HOST, "/secret/open"): text("o")}
    )

    assert fetcher.fetch(f"https://{HOST}/secret/x").status == "disallowed"
    assert fetcher.fetch(f"https://{HOST}/secret/open").status == "fetched"
    assert "/secret/x" not in paths(site)


def test_a_missing_robots_txt_allows_crawling() -> None:
    _, fetcher, recorded = setup({(HOST, "/a"): text("A")})  # robots.txt and tdmrep: 404
    assert fetcher.fetch(f"https://{HOST}/a").status == "fetched"
    assert recorded[0].robots_result == "missing" and recorded[0].decision == "allowed"


@pytest.mark.parametrize("status", [500, 503, 429])
def test_an_unreachable_robots_txt_means_the_domain_is_not_crawled_and_is_logged(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    site, fetcher, recorded = setup({ROBOTS: text("", status), (HOST, "/a"): text("A")})

    with caplog.at_level(logging.WARNING):
        assert fetcher.fetch(f"https://{HOST}/a").status == "not_crawled"

    assert "/a" not in paths(site)
    assert recorded[0].robots_result == "unreachable" and recorded[0].decision == "not_crawled"
    assert "not crawled in this run" in caplog.text


def test_a_timeout_of_robots_txt_means_the_domain_is_not_crawled() -> None:
    site = MockSite({(HOST, "/a"): text("A")})

    def fail(request: httpx2.Request) -> None:
        raise httpx2.ReadTimeout("slow", request=request)

    site.error = fail
    recorded: list[DomainPermission] = []
    client = build_client(CONTACT, resolver=RESOLVER, inner_transport=site.transport)

    result = PermittedFetcher(client, EmptySuppressionList(), recorded.append).fetch(
        f"https://{HOST}/a"
    )

    assert result.status == "not_crawled" and recorded[0].robots_result == "unreachable"


def test_an_unreachable_tdmrep_json_means_the_domain_is_not_crawled() -> None:
    _, fetcher, recorded = setup({TDMREP: text("", 502), (HOST, "/a"): text("A")})
    assert fetcher.fetch(f"https://{HOST}/a").status == "not_crawled"
    assert recorded[0].decision == "not_crawled"


def test_a_suppressed_domain_is_not_contacted_at_all() -> None:
    site, fetcher, recorded = setup({(HOST, "/a"): text("A")}, Suppressed(HOST))

    assert fetcher.fetch(f"https://{HOST}/a").status == "excluded"

    assert site.seen == []
    assert recorded[0].suppression_hit and recorded[0].decision == "excluded"


def test_every_request_names_the_service_and_the_contact_page() -> None:
    site, fetcher, _ = setup({(HOST, "/a"): text("A")})
    fetcher.fetch(f"https://{HOST}/a")
    assert len(site.seen) == 3
    for request in site.seen:
        assert request.user_agent == f"SupplierIScan/1.0 (+{CONTACT})"


def test_the_user_agent_needs_a_configured_contact_page() -> None:
    with pytest.raises(ConfigurationError):
        crawler_user_agent(None)
    with pytest.raises(ConfigurationError):
        build_client(None)


def test_the_contact_page_setting_must_be_an_http_address() -> None:
    assert load_settings({"CRAWLER_CONTACT_URL": CONTACT}).crawler_contact_url == CONTACT
    assert load_settings({}).crawler_contact_url is None
    for bad in ("iscan.example", "javascript:alert(1)", "https://x.example/a b", "https://x/)"):
        with pytest.raises(ConfigurationError):
            load_settings({"CRAWLER_CONTACT_URL": bad})


@pytest.mark.parametrize("status", [401, 403])
def test_a_401_or_403_is_recorded_as_blocked_and_never_retried(status: int) -> None:
    site, fetcher, recorded = setup({(HOST, "/a"): text("no", status), (HOST, "/b"): text("B")})

    assert fetcher.fetch(f"https://{HOST}/a").status == "blocked"
    assert fetcher.fetch(f"https://{HOST}/a").status == "blocked"
    assert fetcher.fetch(f"https://{HOST}/b").status == "blocked"

    assert paths(site).count("/a") == 1 and "/b" not in paths(site)
    assert recorded[-1].decision == "blocked"


def test_a_captcha_page_is_recorded_as_blocked() -> None:
    page = text('<html><div class="g-recaptcha" data-sitekey="k"></div></html>')
    site, fetcher, recorded = setup({(HOST, "/a"): page})

    result = fetcher.fetch(f"https://{HOST}/a")

    assert result.status == "blocked" and result.response is None
    assert recorded[-1].decision == "blocked"
    assert paths(site).count("/a") == 1


def test_a_robots_401_means_the_domain_is_not_crawled() -> None:
    _, fetcher, recorded = setup({ROBOTS: text("", 401), (HOST, "/a"): text("A")})
    assert fetcher.fetch(f"https://{HOST}/a").status == "not_crawled"
    assert recorded[0].robots_result == "blocked"


def test_a_page_carrying_a_tdm_reservation_header_excludes_the_domain() -> None:
    site, fetcher, recorded = setup({(HOST, "/a"): tdm("A"), (HOST, "/b"): text("B")})

    assert fetcher.fetch(f"https://{HOST}/a").status == "excluded"
    assert fetcher.fetch(f"https://{HOST}/b").status == "excluded"
    assert "/b" not in paths(site) and recorded[-1].decision == "excluded"


def test_a_redirect_to_another_domain_is_vetted_before_the_page_is_kept() -> None:
    _, fetcher, recorded = setup(
        {
            (HOST, "/a"): httpx2.Response(302, headers={"Location": "https://other.example/x"}),
            ("other.example", "/robots.txt"): text("User-agent: CCBot\nDisallow: /\n"),
            ("other.example", "/x"): text("X"),
        }
    )

    assert fetcher.fetch(f"https://{HOST}/a").status == "excluded"
    assert {p.domain for p in recorded} == {HOST, "other.example"}


def test_protego_reads_longest_match() -> None:
    robots = Protego.parse("User-agent: *\nDisallow: /a\nAllow: /a/b\n")
    assert robots.can_fetch("https://x/a/b", "SupplierIScan")
    assert not robots.can_fetch("https://x/a/c", "SupplierIScan")


def test_the_exclusion_message() -> None:
    assert EXCLUSION_MESSAGE == "Source excluded at the site owner's request."


def test_check_domain_returns_the_permission_without_a_fetcher() -> None:
    site = MockSite({})
    client = build_client(CONTACT, resolver=RESOLVER, inner_transport=site.transport)
    permission = check_domain(client, f"https://{HOST}/", EmptySuppressionList())
    assert permission.decision == "allowed"
