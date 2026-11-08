"""The ceiling on all outbound requests of one collection run (#103).

`COLLECT_MAX_ATTEMPTS` counts requests for content only. This budget counts every request the
guarded client sends for the run: robots.txt and TDM permission checks, every redirect hop, every
retry. It also caps the distinct domains contacted, so that a redirect chain reaching a new domain
at every hop (or a hostile sitemap) cannot spread the run over the web. It is attached to the
client as its `before_request` hook, so no code path can bypass it.
"""

import threading
from dataclasses import dataclass, field
from typing import Protocol


class HasHost(Protocol):
    @property
    def host(self) -> str: ...


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
    sent: int = 0
    domains: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def __call__(self, url: HasHost) -> None:
        with self._lock:
            self._count(url.host.lower().removeprefix("www."))

    def _count(self, domain: str) -> None:
        if self.sent >= self.max_requests:
            raise RequestLimitReached
        if domain not in self.domains:
            if len(self.domains) >= self.max_domains:
                raise DomainLimitReached(domain)
            self.domains.add(domain)
        self.sent += 1
