"""URL guard: URL validation and address vetting for every outgoing fetch to a supplier site.

Spec: F1 (website fallback), F2 (targets resolving to private, loopback or link-local addresses are
refused), Robustness cases (URL pointing to a private network address; malformed input).

Two steps, both before any connection:

1. `validate_url` / `normalise_url`: only `http` and `https`, no embedded credentials, a valid host
   name (internationalised names are converted to punycode) or IP literal, a valid port.
2. `resolve_and_vet`: one resolution of the host; every address it returns must be public. The
   caller then connects to one of these addresses and never resolves the name again (no DNS
   rebinding window), see `transport.GuardedTransport`.
"""

import ipaddress
import logging
import re
import socket
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

import httpx2

from app.http_client.errors import (
    BlockedAddressError,
    DnsResolutionError,
    FetchTimeoutError,
    InvalidUrlError,
)

logger = logging.getLogger(__name__)

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Sequence[IPAddress]]

ALLOWED_SCHEMES = frozenset({"http", "https"})
DEFAULT_PORTS = {"http": 80, "https": 443}

_MAX_HOST_LENGTH = 253
# One DNS label after IDNA conversion: letters, digits, hyphens; no leading or trailing hyphen.
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
# "scheme://..." at the start of the input.
_HAS_AUTHORITY_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
# "scheme:..." without "//" (javascript:, mailto:, data:), told apart from "host:port".
_HOST_WITH_PORT = re.compile(r"^[^/?#:@]+:\d+(?:[/?#]|$)")
_OPAQUE_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

# Well-known NAT64 prefix (RFC 6052): the last 32 bits are an IPv4 address.
_NAT64_PREFIX = ipaddress.IPv6Network("64:ff9b::/96")

MSG_EMPTY = "Enter a website address."
MSG_MALFORMED = "This is not a valid web address."
MSG_SCHEME = "Only web addresses starting with http:// or https:// are accepted."
MSG_CREDENTIALS = "The web address must not contain a user name or password."
MSG_HOST = "The web address does not contain a valid domain name."
MSG_PORT = "The web address contains an invalid port number."
MSG_BLOCKED = (
    "This address points to a private or internal network, which Supplier iScan does not access."
)


def normalise_url(raw: str, *, assume_https: bool = False) -> httpx2.URL:
    """Parse and validate member or page input; return the URL with an ASCII (punycode) host.

    With `assume_https`, a bare domain such as `example.com` or `münchen.de/about` gets `https://`.
    Raises `InvalidUrlError` with a plain-language message.
    """
    text = (raw or "").strip()
    if not text:
        raise InvalidUrlError(MSG_EMPTY)
    if any(character.isspace() or ord(character) < 32 for character in text):
        raise InvalidUrlError(MSG_MALFORMED)
    if not _HAS_AUTHORITY_SCHEME.match(text):
        if _OPAQUE_SCHEME.match(text) and not _HOST_WITH_PORT.match(text):
            raise InvalidUrlError(MSG_SCHEME)
        if not assume_https:
            raise InvalidUrlError(MSG_MALFORMED)
        text = "https://" + text
    try:
        url = httpx2.URL(text)
    except (httpx2.InvalidURL, UnicodeError, ValueError) as error:
        raise InvalidUrlError(MSG_MALFORMED) from error
    return validate_url(url)


def has_explicit_scheme(raw: str) -> bool:
    """True for `scheme://...` input, false for a bare domain such as `example.com/about`."""
    return bool(_HAS_AUTHORITY_SCHEME.match((raw or "").strip()))


def validate_url(url: httpx2.URL) -> httpx2.URL:
    """Check an already parsed URL (also every redirect target); return it with an ASCII host."""
    if url.scheme not in ALLOWED_SCHEMES:
        raise InvalidUrlError(MSG_SCHEME)
    if url.userinfo:
        raise InvalidUrlError(MSG_CREDENTIALS)
    port = url.port
    if port is not None and not 1 <= port <= 65535:
        raise InvalidUrlError(MSG_PORT)
    # ASCII (punycode) host, and "/" for an empty path, so that equal URLs print the same.
    return url.copy_with(host=_ascii_host(url), path=url.path)


def _ascii_host(url: httpx2.URL) -> str:
    try:
        host = url.raw_host.decode("ascii").lower()
    except UnicodeDecodeError as error:
        raise InvalidUrlError(MSG_HOST) from error
    if not host:
        raise InvalidUrlError(MSG_HOST)
    if _ip_literal(host) is not None:
        return host
    host = host.removesuffix(".")
    if len(host) > _MAX_HOST_LENGTH or not all(_LABEL.match(label) for label in host.split(".")):
        raise InvalidUrlError(MSG_HOST)
    return host


def _ip_literal(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def port_of(url: httpx2.URL) -> int:
    return url.port or DEFAULT_PORTS[url.scheme]


def _embedded_ipv4(address: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """IPv4 addresses carried inside an IPv6 address (mapped, 6to4, Teredo, NAT64)."""
    embedded: list[ipaddress.IPv4Address] = []
    if address.ipv4_mapped is not None:
        embedded.append(address.ipv4_mapped)
    if address.sixtofour is not None:
        embedded.append(address.sixtofour)
    if address.teredo is not None:
        embedded.extend(address.teredo)
    if address in _NAT64_PREFIX:
        embedded.append(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    return embedded


def is_public_address(address: IPAddress) -> bool:
    """True only for globally routable unicast addresses.

    Refused: private (RFC 1918), shared (100.64/10), loopback, link-local (including
    169.254.169.254), unique-local and site-local IPv6, unspecified, multicast, reserved and
    documentation ranges, and any IPv6 address that embeds one of these IPv4 addresses
    (IPv4-mapped, 6to4, Teredo, NAT64). Python classes the whole NAT64 prefix 64:ff9b::/96 as
    reserved, so NAT64 addresses are refused even when they carry a public IPv4 address.
    """
    if isinstance(address, ipaddress.IPv6Address):
        address = ipaddress.IPv6Address(int(address))  # drop any "%scope" zone
        embedded = _embedded_ipv4(address)
        if any(not is_public_address(inner) for inner in embedded):
            return False
        if address.ipv4_mapped is not None:
            return True  # decided by the mapped IPv4 address above
        if address.is_site_local:
            return False
    return (
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_private
    )


def system_resolver(host: str, port: int) -> list[IPAddress]:
    """Resolve with the operating system (`socket.getaddrinfo`); TCP addresses, in its order."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as error:
        raise DnsResolutionError(_dns_failure_reason(host)) from error
    addresses: list[IPAddress] = []
    for _family, _type, _proto, _canonname, sockaddr in infos:
        address = ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0])
        if address not in addresses:
            addresses.append(address)
    return addresses


def _dns_failure_reason(host: str) -> str:
    return f"The domain {host} could not be found (DNS lookup failed)."


# getaddrinfo has no timeout of its own: it runs in a small pool so that the caller can stop
# waiting. A resolution that hangs keeps one worker busy until the OS gives up.
_resolution_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="url-guard-dns")


def resolve_and_vet(
    host: str, port: int, resolver: Resolver, timeout: float | None
) -> list[IPAddress]:
    """Resolve `host` once and return its addresses if every one of them is public.

    Raises `BlockedAddressError` if any address is not public (a mixed answer is refused),
    `DnsResolutionError` if the name does not resolve, `FetchTimeoutError` after `timeout` seconds.
    """
    literal = _ip_literal(host)
    if literal is not None:
        addresses: Sequence[IPAddress] = [literal]
    else:
        addresses = _resolve(host, port, resolver, timeout)
        if not addresses:
            raise DnsResolutionError(_dns_failure_reason(host))
    if not all(is_public_address(address) for address in addresses):
        # The resolved addresses stay in the logs of the instance, never in the member's message.
        logger.warning(
            "URL guard refused %s: non-public address %s", host, list(map(str, addresses))
        )
        raise BlockedAddressError(MSG_BLOCKED)
    return list(addresses)


def _resolve(
    host: str, port: int, resolver: Resolver, timeout: float | None
) -> Sequence[IPAddress]:
    try:
        if timeout is None:
            return resolver(host, port)
        future = _resolution_pool.submit(resolver, host, port)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as error:
            future.cancel()
            raise FetchTimeoutError(
                f"The domain {host} did not resolve within {timeout:g} seconds."
            ) from error
    except socket.gaierror as error:  # a resolver other than system_resolver
        raise DnsResolutionError(_dns_failure_reason(host)) from error
