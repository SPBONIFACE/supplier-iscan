"""Criteria 1 and 2: refusal before any connection, pinned connection, checked redirects."""

import socket

import httpx2
import pytest

from app.http_client import (
    BlockedAddressError,
    DnsResolutionError,
    FetchSettings,
    FetchTimeoutError,
    InvalidUrlError,
    TooManyRedirectsError,
)
from app.http_client.url_guard import MSG_CREDENTIALS, MSG_SCHEME
from tests.http_client.support import (
    OTHER_PUBLIC_V4,
    PUBLIC_V4,
    PUBLIC_V6,
    MockSite,
    NetworkSpy,
    SequenceResolver,
    StubResolver,
    make_client,
    redirect,
)

# --- Criterion 1: refused before any connection -------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fe80::1]/",
        "http://[fd00::1]/",
        "http://0.0.0.0/",  # noqa: S104 - a test value, not a bind address
        "http://224.0.0.1/",
        "https://intranet.example.com/",  # resolves to a private address
        "https://metadata.example.com/",  # resolves to 169.254.169.254
        "https://mapped.example.com/",  # resolves to an IPv4-mapped loopback
    ],
)
def test_non_public_targets_are_refused_and_no_socket_is_opened(
    url: str, network: NetworkSpy
) -> None:
    resolver = StubResolver(
        {
            "intranet.example.com": ["10.20.30.40"],
            "metadata.example.com": ["169.254.169.254"],
            "mapped.example.com": ["::ffff:127.0.0.1"],
        }
    )
    # The real transport: had the guard let the request through, the spy would record a socket.
    with make_client(resolver) as client, pytest.raises(BlockedAddressError):
        client.get(url)

    assert network.sockets == []
    assert network.lookups == []


# --- Criterion 2: the connection goes to the vetted address -------------------------------------


def test_the_real_transport_connects_to_the_vetted_address_without_resolving_again(
    network: NetworkSpy,
) -> None:
    resolver = StubResolver({"www.example.com": [PUBLIC_V4]})

    # Sockets are refused by the spy, so the attempt ends in a connection error, after it showed
    # where the transport tried to connect.
    with make_client(resolver) as client, pytest.raises(httpx2.ConnectError):
        client.get("https://www.example.com/about")

    assert resolver.calls == [("www.example.com", 443)]
    assert network.lookups and set(network.lookups) == {PUBLIC_V4}  # numeric only: no DNS
    assert network.sockets == [socket.AF_INET]


def test_the_request_is_pinned_to_the_ip_with_host_header_and_tls_name_kept() -> None:
    site = MockSite({("xn--mnchen-3ya.example:8443", "/"): httpx2.Response(200)})
    resolver = StubResolver({"xn--mnchen-3ya.example": [PUBLIC_V6]})

    with make_client(resolver, site) as client:
        response = client.get("https://münchen.example:8443/")

    assert response.status_code == 200
    assert str(response.url) == "https://xn--mnchen-3ya.example:8443/"
    [seen] = site.seen
    assert seen.connect_host == PUBLIC_V6
    assert seen.url == f"https://[{PUBLIC_V6}]:8443/"
    assert seen.host_header == "xn--mnchen-3ya.example:8443"
    assert seen.sni_hostname == "xn--mnchen-3ya.example"


def test_a_dns_answer_that_changes_after_the_check_cannot_redirect_the_connection() -> None:
    site = MockSite({("rebind.example", "/"): httpx2.Response(200)})
    resolver = SequenceResolver([PUBLIC_V4], ["127.0.0.1"])

    with make_client(resolver, site) as client:
        assert client.get("http://rebind.example/").status_code == 200
        # One resolution per request: the connection used the vetted address.
        assert resolver.calls == ["rebind.example"]
        assert [seen.connect_host for seen in site.seen] == [PUBLIC_V4]
        # The next request resolves again, gets the private answer and is refused.
        with pytest.raises(BlockedAddressError):
            client.get("http://rebind.example/")

    assert len(site.seen) == 1


def test_the_next_vetted_address_is_tried_when_a_connection_fails() -> None:
    site = MockSite({("dual.example", "/"): httpx2.Response(200)})

    def refuse_first_address(request: httpx2.Request) -> None:
        if request.url.host == PUBLIC_V4:
            raise httpx2.ConnectError("refused", request=request)

    site.error = refuse_first_address
    resolver = StubResolver({"dual.example": [PUBLIC_V4, OTHER_PUBLIC_V4]})

    with make_client(resolver, site) as client:
        assert client.get("http://dual.example/").status_code == 200

    assert [seen.connect_host for seen in site.seen] == [PUBLIC_V4, OTHER_PUBLIC_V4]
    assert resolver.calls == [("dual.example", 80)]


def test_environment_proxies_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # A proxy would receive the connection instead of the vetted address.
    monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.99:3128")
    monkeypatch.setenv("ALL_PROXY", "http://10.0.0.99:3128")
    site = MockSite({("www.example.com", "/"): httpx2.Response(200)})

    with make_client(StubResolver({"www.example.com": [PUBLIC_V4]}), site) as client:
        assert client.get("https://www.example.com/").status_code == 200

    assert site.seen[0].connect_host == PUBLIC_V4


# --- Criterion 2: every redirect is checked again -----------------------------------------------

RESOLVER_ANSWERS = {
    "www.example.com": [PUBLIC_V4],
    "example.com": [PUBLIC_V4],
    "intranet.example.com": ["192.168.0.10"],
    "metadata.example.com": ["169.254.169.254"],
}


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/admin",
        "http://10.0.0.1/",
        "http://[::1]:8080/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::ffff:169.254.169.254]/",
        "https://intranet.example.com/",
        "//metadata.example.com/computeMetadata/v1/",
    ],
)
def test_a_redirect_to_a_non_public_target_is_refused_before_connecting(
    location: str, network: NetworkSpy
) -> None:
    site = MockSite({("www.example.com", "/"): redirect(location)})

    with make_client(StubResolver(RESOLVER_ANSWERS), site) as client:
        with pytest.raises(BlockedAddressError):
            client.get("https://www.example.com/")

    assert len(site.seen) == 1  # only the first hop reached the transport
    assert network.sockets == []


@pytest.mark.parametrize(
    ("location", "message"),
    [
        ("file:///etc/passwd", MSG_SCHEME),
        ("ftp://www.example.com/file", MSG_SCHEME),
        ("http://user:secret@www.example.com/", MSG_CREDENTIALS),
    ],
)
def test_a_redirect_to_another_scheme_or_with_credentials_is_refused(
    location: str, message: str
) -> None:
    site = MockSite({("www.example.com", "/"): redirect(location)})

    with make_client(StubResolver(RESOLVER_ANSWERS), site) as client:
        with pytest.raises(InvalidUrlError) as raised:
            client.get("https://www.example.com/")

    assert raised.value.reason == message
    assert len(site.seen) == 1


def test_relative_and_cross_host_redirects_are_followed_and_checked() -> None:
    site = MockSite(
        {
            ("example.com", "/"): redirect("https://www.example.com/", 301),
            ("www.example.com", "/"): redirect("/en/home", 308),
            ("www.example.com", "/en/home"): httpx2.Response(200, text="Welcome"),
        }
    )
    resolver = StubResolver(RESOLVER_ANSWERS)

    with make_client(resolver, site) as client:
        response = client.get("http://example.com/")

    assert response.text == "Welcome"
    assert str(response.url) == "https://www.example.com/en/home"
    assert resolver.calls == [
        ("example.com", 80),
        ("www.example.com", 443),
        ("www.example.com", 443),
    ]


@pytest.mark.parametrize("max_redirects", [0, 1, 3])
def test_redirects_stop_at_the_configured_maximum(max_redirects: int) -> None:
    pages = {("www.example.com", f"/{n}"): redirect(f"/{n + 1}") for n in range(10)}
    site = MockSite(pages)
    settings = FetchSettings(max_redirects=max_redirects)

    with make_client(StubResolver(RESOLVER_ANSWERS), site, settings) as client:
        with pytest.raises(TooManyRedirectsError, match=f"more than {max_redirects} times"):
            client.get("https://www.example.com/0")

    assert len(site.seen) == max_redirects + 1


def test_a_chain_within_the_maximum_succeeds() -> None:
    pages = {("www.example.com", f"/{n}"): redirect(f"/{n + 1}") for n in range(3)}
    pages[("www.example.com", "/3")] = httpx2.Response(200)
    site = MockSite(pages)

    with make_client(StubResolver(RESOLVER_ANSWERS), site, FetchSettings(max_redirects=3)) as c:
        assert c.get("https://www.example.com/0").status_code == 200


def test_the_redirect_chain_shares_one_deadline() -> None:
    timeouts: list[float] = []
    site = MockSite(
        {
            ("www.example.com", "/a"): redirect("/b"),
            ("www.example.com", "/b"): httpx2.Response(200),
        }
    )

    def record_timeout(request: httpx2.Request) -> None:
        timeouts.append(request.extensions["timeout"]["read"])

    site.error = record_timeout

    with make_client(StubResolver(RESOLVER_ANSWERS), site) as client:
        client.get("https://www.example.com/a", timeout=5)

    assert len(timeouts) == 2
    assert 0 < timeouts[1] <= timeouts[0] <= 5


def test_an_exhausted_deadline_is_a_timeout() -> None:
    site = MockSite({("www.example.com", "/"): httpx2.Response(200)})

    with make_client(StubResolver(RESOLVER_ANSWERS), site) as client:
        with pytest.raises(FetchTimeoutError):
            client.get("https://www.example.com/", timeout=0)

    assert site.seen == []


def test_an_unknown_name_is_a_dns_failure() -> None:
    with make_client(StubResolver(), MockSite()) as client:
        with pytest.raises(DnsResolutionError):
            client.get("https://nowhere.example/")


def test_a_request_built_outside_the_client_helpers_is_still_guarded(
    network: NetworkSpy,
) -> None:
    # The guard sits in the transport: it also covers a request sent on the underlying client.
    with make_client(StubResolver()) as client:
        assert not hasattr(client, "_client")  # name-mangled: not reachable by accident
        raw_client = client._GuardedClient__client  # type: ignore[attr-defined]  # noqa: SLF001
        with pytest.raises(BlockedAddressError):
            raw_client.get("http://127.0.0.1/")
        with pytest.raises(InvalidUrlError):
            raw_client.get("http://user:pw@93.184.215.14/")

    assert network.sockets == []


@pytest.mark.parametrize(
    "location", ["javascript:alert(1)", "mailto:a@b.c", "data:text/html,x", "http://[::1"]
)
def test_a_redirect_that_httpx2_cannot_parse_is_an_invalid_url_error(location: str) -> None:
    site = MockSite({("www.example.com", "/"): redirect(location)})

    with (
        make_client(StubResolver({"www.example.com": [PUBLIC_V4]}), site) as client,
        pytest.raises(InvalidUrlError),
    ):
        client.get("https://www.example.com/")

    assert len(site.seen) == 1


@pytest.mark.parametrize("location", ["//@www.example.com/x", "https://@www.example.com/x"])
def test_a_redirect_with_an_empty_user_name_is_refused(location: str) -> None:
    site = MockSite({("www.example.com", "/"): redirect(location)})

    with (
        make_client(StubResolver({"www.example.com": [PUBLIC_V4]}), site) as client,
        pytest.raises(InvalidUrlError, match="user name or password"),
    ):
        client.get("https://www.example.com/")

    assert len(site.seen) == 1


def test_an_ipv6_literal_is_bracketed_in_the_host_header() -> None:
    site = MockSite(
        {
            (f"[{PUBLIC_V6}]", "/"): httpx2.Response(200),
            (f"[{PUBLIC_V6}]:8080", "/"): httpx2.Response(200),
        }
    )

    with make_client(StubResolver(), site) as client:
        assert client.get(f"http://[{PUBLIC_V6}]/").status_code == 200
        assert client.get(f"http://[{PUBLIC_V6}]:8080/").status_code == 200

    assert [seen.host_header for seen in site.seen] == [f"[{PUBLIC_V6}]", f"[{PUBLIC_V6}]:8080"]
