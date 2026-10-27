"""Criterion 1, at the address level: which resolved addresses the guard refuses."""

import ipaddress
import socket
import time

import pytest

from app.http_client import (
    BlockedAddressError,
    DnsResolutionError,
    FetchTimeoutError,
    is_public_address,
)
from app.http_client.url_guard import IPAddress, resolve_and_vet, system_resolver
from tests.http_client.support import PUBLIC_V4, PUBLIC_V6, StubResolver


@pytest.mark.parametrize(
    "address",
    [
        # IPv4: private (RFC 1918), loopback, link-local and cloud metadata, shared, unspecified,
        # multicast, broadcast, reserved, documentation, benchmarking
        "10.0.0.1",
        "172.16.5.4",
        "192.168.1.1",
        "127.0.0.1",
        "127.255.255.254",
        "169.254.169.254",
        "169.254.0.1",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104 - a test value, not a bind address
        "224.0.0.1",
        "224.0.1.1",
        "239.255.255.250",
        "255.255.255.255",
        "240.0.0.1",
        "192.0.2.10",
        "198.18.0.1",
        # IPv6: loopback, unspecified, link-local (with and without zone), unique-local,
        # site-local, multicast, documentation
        "::1",
        "::",
        "fe80::1",
        "fe80::1%eth0",
        "fc00::1",
        "fd12:3456:789a::1",
        "fec0::1",
        "ff02::1",
        "ff0e::1",
        "2001:db8::1",
        # IPv6 addresses carrying a non-public IPv4 address
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",
        "::127.0.0.1",
        "2002:7f00:1::",  # 6to4 of 127.0.0.1
        "2002:a00:1::",  # 6to4 of 10.0.0.1
        "64:ff9b::a00:1",  # NAT64 of 10.0.0.1
        "64:ff9b::a9fe:a9fe",  # NAT64 of 169.254.169.254
        "64:ff9b::808:808",  # NAT64 of 8.8.8.8: the whole prefix is reserved, refused too
        "2001:0:4136:e378:8000:63bf:f5ff:fffe",  # Teredo, client 10.0.0.1
    ],
)
def test_non_public_addresses_are_refused(address: str) -> None:
    assert not is_public_address(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", [PUBLIC_V4, "8.8.8.8", PUBLIC_V6, "::ffff:93.184.215.14"])
def test_public_addresses_are_allowed(address: str) -> None:
    assert is_public_address(ipaddress.ip_address(address))


def test_a_name_resolving_to_one_private_address_among_public_ones_is_refused() -> None:
    resolver = StubResolver({"mixed.example": [PUBLIC_V4, "10.0.0.7"]})

    with pytest.raises(BlockedAddressError) as raised:
        resolve_and_vet("mixed.example", 443, resolver, timeout=1)

    assert "10.0.0.7" not in raised.value.reason  # no internal detail in the member's message


def test_an_ip_literal_is_vetted_without_any_resolution() -> None:
    resolver = StubResolver()

    with pytest.raises(BlockedAddressError):
        resolve_and_vet("127.0.0.1", 80, resolver, timeout=1)
    assert resolve_and_vet(PUBLIC_V4, 80, resolver, timeout=1) == [ipaddress.ip_address(PUBLIC_V4)]
    assert resolver.calls == []


def test_unknown_names_and_empty_answers_are_dns_failures() -> None:
    resolver = StubResolver({"empty.example": []})

    with pytest.raises(DnsResolutionError, match="nowhere.example could not be found"):
        resolve_and_vet("nowhere.example", 443, resolver, timeout=1)
    with pytest.raises(DnsResolutionError):
        resolve_and_vet("empty.example", 443, resolver, timeout=1)


def test_a_resolution_that_hangs_stops_at_the_timeout() -> None:
    def slow(host: str, port: int) -> list[IPAddress]:
        time.sleep(0.5)
        return [ipaddress.ip_address(PUBLIC_V4)]

    started = time.monotonic()
    with pytest.raises(FetchTimeoutError):
        resolve_and_vet("slow.example", 443, slow, timeout=0.05)
    assert time.monotonic() - started < 0.4


def test_system_resolver_reads_getaddrinfo_and_drops_duplicates_and_zones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        calls.append(args)
        tcp = (socket.SOCK_STREAM, socket.IPPROTO_TCP, "")
        return [
            (socket.AF_INET6, *tcp, (PUBLIC_V6, 443, 0, 0)),
            (socket.AF_INET, *tcp, (PUBLIC_V4, 443)),
            (socket.AF_INET, *tcp, (PUBLIC_V4, 443)),
            (socket.AF_INET6, *tcp, ("fe80::1%en0", 443, 0, 4)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    assert system_resolver("example.com", 443) == [
        ipaddress.ip_address(PUBLIC_V6),
        ipaddress.ip_address(PUBLIC_V4),
        ipaddress.ip_address("fe80::1"),
    ]
    assert calls == [("example.com", 443)]


def test_system_resolver_turns_a_lookup_failure_into_a_dns_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", failing_getaddrinfo)

    with pytest.raises(DnsResolutionError):
        system_resolver("nowhere.example", 443)
