"""The ceiling on all outbound requests of one collection run (#103).

`COLLECT_MAX_ATTEMPTS` counts requests for content only. This budget counts every request the
guarded client sends for the run: robots.txt and TDM permission checks, every redirect hop, every
retry. It also caps the distinct domains contacted, so that a redirect chain reaching a new domain
at every hop (or a hostile sitemap) cannot spread the run over the web. It is attached to the
client as its `before_request` hook, so no code path can bypass it.
"""

from dataclasses import dataclass, field

import httpx2


class RequestLimitReached(Exception):
    """The run has sent as many requests as it may; none is sent beyond."""


class DomainLimitReached(Exception):
    """The run has contacted as many distinct domains as it may; this one is refused."""

    def __init__(self, domain: str) -> None:
        super().__init__(domain)
        self.domain = domain


@dataclass
class RequestBudget:
    max_requests: int
    max_domains: int
    requests: int = 0
    domains: set[str] = field(default_factory=set)

    def __call__(self, url: httpx2.URL) -> None:
        domain = url.host.lower().removeprefix("www.")
        if self.requests >= self.max_requests:
            raise RequestLimitReached
        if domain not in self.domains:
            if len(self.domains) >= self.max_domains:
                raise DomainLimitReached(domain)
            self.domains.add(domain)
        self.requests += 1
