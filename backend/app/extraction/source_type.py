"""Source type and attribution of a fact (spec F3; owner decision, 27 Oct 2026).

`supplier_claim` ("Supplier's own claim") when the source is
- on the domain of the confirmed supplier website, or one of its subdomains, with or without
  `www`; or
- on a domain listed in the identity's registry identifiers; or
- a PDF linked from a page of the confirmed supplier website, even when hosted on another domain.

`third_party` ("Third-party source") otherwise. Domains are compared whole: a country variant
(`acme.fr` for `acme.com`) or a look-alike (`notacme.com`) is not the supplier's domain unless a
registry identifier lists it. No public-suffix list is needed: the supplier's own host is the
anchor, so `acme.co.uk` has the subdomains `*.acme.co.uk` and nothing else.
"""

from collections.abc import Iterable
from typing import Any, Literal
from urllib.parse import urlsplit

SourceType = Literal["supplier_claim", "third_party"]


def host_of(url: str) -> str | None:
    """The lower-case host without `www.`, or None when the address has none."""
    try:
        host = (urlsplit(url if "//" in url else "//" + url).hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    host = host.removeprefix("www.")
    return host or None


# Official registers whose pages are built by the collection itself (#142): the public GLEIF
# record page. Their sources are independent of the supplier, so `classify_source` types them
# `third_party` (the contract has no third value); `is_official_register` tells them apart.
OFFICIAL_REGISTER_HOSTS = frozenset({"search.gleif.org"})


def is_official_register(url: str) -> bool:
    host = host_of(url)
    return host is not None and host in OFFICIAL_REGISTER_HOSTS


def _is_own(host: str, own: str) -> bool:
    return host == own or host.endswith("." + own)


def registry_domains(registry_ids: dict[str, Any] | None) -> set[str]:
    """The domains the identity's registry identifiers list: any value (or item of a list value)
    that is an address or a host name. Identifiers such as an LEI or a Wikidata id are not."""
    found: set[str] = set()

    def add(value: object) -> None:
        if isinstance(value, list | tuple):
            for item in value:
                add(item)
        elif isinstance(value, str) and "." in value and not any(c.isspace() for c in value):
            host = host_of(value)
            if host and "." in host:
                found.add(host)

    for value in (registry_ids or {}).values():
        add(value)
    return found


def classify_source(
    url: str,
    website: str | None,
    registry_hosts: Iterable[str] = (),
    linked_from_url: str | None = None,
) -> SourceType:
    """`linked_from_url`: the page that linked to this source (a PDF), when the collection
    recorded it (`Source.linked_from_source_id`)."""
    own = host_of(website) if website else None
    host = host_of(url)
    if host is None:
        return "third_party"
    if own and _is_own(host, own):
        return "supplier_claim"
    if any(_is_own(host, registry) for registry in registry_hosts):
        return "supplier_claim"
    if own and linked_from_url:
        page = host_of(linked_from_url)
        if page and _is_own(page, own):
            return "supplier_claim"
    return "third_party"
