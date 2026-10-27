"""Criterion 5: the website check for the "enter the website" fallback."""

import ipaddress
import ssl
import time

import httpx2
import pytest

from app.http_client import FetchSettings, WebsiteCheckResult, check_website
from app.http_client.url_guard import IPAddress
from tests.http_client.support import (
    PUBLIC_V4,
    MockSite,
    NetworkSpy,
    StubResolver,
    make_client,
    redirect,
)

ANSWERS = {
    "acme.example": [PUBLIC_V4],
    "www.acme.example": [PUBLIC_V4],
    "xn--mnchen-3ya.de": [PUBLIC_V4],
    "www.xn--mnchen-3ya.de": [PUBLIC_V4],
    "intranet.acme.example": ["10.1.2.3"],
}


def check(
    raw: str, site: MockSite, settings: FetchSettings | None = None, resolver: object = None
) -> WebsiteCheckResult:
    with make_client(resolver or StubResolver(ANSWERS), site, settings) as client:  # type: ignore[arg-type]
        return check_website(raw, client)


@pytest.mark.parametrize("raw", ["acme.example", "https://acme.example", "  ACME.example/  "])
def test_a_responding_site_is_reachable_with_its_final_domain_after_redirects(raw: str) -> None:
    site = MockSite(
        {
            ("acme.example", "/"): redirect("https://www.acme.example/en/"),
            ("www.acme.example", "/en/"): httpx2.Response(200),
        }
    )

    result = check(raw, site)

    assert result == WebsiteCheckResult(
        status="reachable",
        final_domain="www.acme.example",
        final_url="https://www.acme.example/en/",
    )


def test_an_internationalised_domain_is_checked_in_punycode() -> None:
    site = MockSite(
        {
            ("xn--mnchen-3ya.de", "/"): httpx2.Response(
                301, headers={b"Location": "https://www.münchen.de/".encode()}
            ),
            ("www.xn--mnchen-3ya.de", "/"): httpx2.Response(200),
        }
    )

    result = check("münchen.de", site)

    assert result.status == "reachable"
    assert result.final_domain == "www.xn--mnchen-3ya.de"


def test_dns_failure_gives_a_plain_language_reason() -> None:
    result = check("unknown-supplier.example", MockSite())

    assert result.status == "unreachable"
    assert result.failure == "dns_failure"
    assert result.reason == (
        "The domain unknown-supplier.example could not be found (DNS lookup failed)."
    )
    assert result.final_domain is None


def test_a_server_that_does_not_answer_in_time_is_a_timeout() -> None:
    site = MockSite()

    def hang(request: httpx2.Request) -> None:
        raise httpx2.ReadTimeout("timed out", request=request)

    site.error = hang

    result = check("acme.example", site, FetchSettings(website_check_timeout_seconds=3))

    assert result.failure == "timeout"
    assert result.reason == "The website did not respond within 3 seconds."


def test_a_resolution_that_hangs_ends_within_the_configured_timeout() -> None:
    def slow(host: str, port: int) -> list[IPAddress]:
        time.sleep(1)
        return [ipaddress.ip_address(PUBLIC_V4)]

    started = time.monotonic()
    result = check(
        "acme.example", MockSite(), FetchSettings(website_check_timeout_seconds=0.1), slow
    )

    assert result.failure == "timeout"
    assert result.reason == "The website did not respond within 0.1 seconds."
    assert time.monotonic() - started < 0.8


@pytest.mark.parametrize(("status", "phrase"), [(404, "Not Found"), (503, "Service Unavailable")])
def test_an_http_error_gives_the_status_in_plain_language(status: int, phrase: str) -> None:
    site = MockSite({("acme.example", "/"): httpx2.Response(status)})

    result = check("https://acme.example", site)

    assert result.failure == "http_error"
    assert result.http_status == status
    assert result.reason == f"The website answered with an error (HTTP {status} {phrase})."


def test_a_bare_domain_falls_back_to_http_when_https_cannot_connect() -> None:
    site = MockSite({("acme.example", "/"): httpx2.Response(200)})

    def no_tls(request: httpx2.Request) -> None:
        if request.url.scheme == "https":
            raise httpx2.ConnectError("connection refused", request=request)

    site.error = no_tls

    result = check("acme.example", site)

    assert result.status == "reachable"
    assert result.final_url == "http://acme.example/"


def test_an_explicit_https_url_does_not_fall_back_to_http() -> None:
    site = MockSite({("acme.example", "/"): httpx2.Response(200)})

    def refuse(request: httpx2.Request) -> None:
        raise httpx2.ConnectError("connection refused", request=request)

    site.error = refuse

    result = check("https://acme.example", site)

    assert result.failure == "connection_failed"
    assert result.reason is not None and "could not be reached" in result.reason
    assert len(site.seen) == 1


def test_an_invalid_certificate_is_reported_and_never_bypassed_over_http() -> None:
    site = MockSite({("acme.example", "/"): httpx2.Response(200)})

    def bad_certificate(request: httpx2.Request) -> None:
        if request.url.scheme == "https":
            try:
                raise ssl.SSLCertVerificationError("certificate verify failed: Hostname mismatch")
            except ssl.SSLError as tls_error:
                raise httpx2.ConnectError(str(tls_error), request=request) from tls_error

    site.error = bad_certificate

    result = check("acme.example", site)

    assert result.failure == "certificate_invalid"
    assert result.reason == (
        "The website's security certificate is not valid for this domain or has expired."
    )
    assert [seen.url.split(":", 1)[0] for seen in site.seen] == ["https"]


def test_an_invalid_response_is_reported_without_crashing() -> None:
    site = MockSite()

    def broken(request: httpx2.Request) -> None:
        raise httpx2.RemoteProtocolError("malformed status line", request=request)

    site.error = broken

    assert check("acme.example", site).failure == "invalid_response"


@pytest.mark.parametrize(
    ("raw", "failure"),
    [
        ("", "invalid_url"),
        ("ftp://acme.example", "invalid_url"),
        ("javascript:alert(1)", "invalid_url"),
        ("https://admin:pw@acme.example", "invalid_url"),
        ("127.0.0.1", "blocked_address"),
        ("intranet.acme.example", "blocked_address"),
        ("http://[::1]:8080", "blocked_address"),
    ],
)
def test_invalid_or_private_input_is_unreachable_without_any_connection(
    raw: str, failure: str, network: NetworkSpy
) -> None:
    site = MockSite()

    result = check(raw, site)

    assert result.status == "unreachable"
    assert result.failure == failure
    assert result.reason
    assert site.seen == []
    assert network.sockets == []


def test_a_redirect_into_a_private_network_is_reported_as_blocked() -> None:
    site = MockSite({("acme.example", "/"): redirect("http://169.254.169.254/")})

    result = check("acme.example", site)

    assert result.failure == "blocked_address"
    assert result.reason is not None and "private or internal network" in result.reason


def test_too_many_redirects_is_reported() -> None:
    site = MockSite({("acme.example", "/"): redirect("/")})

    result = check("acme.example", site, FetchSettings(max_redirects=2))

    assert result.failure == "too_many_redirects"
    assert result.reason == "The website redirected more than 2 times."
