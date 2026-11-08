"""The fetcher of a supplier's pages: permissions first, identity on every request (spec F2).

`PermittedFetcher.fetch(url)` checks the domain once (robots.txt, `tdm-reservation`,
`tdmrep.json`, the suppression list), records the result, and then fetches only what the signals
allow, with the guarded client of #15. A 401, a 403 or a CAPTCHA page marks the domain `blocked`:
it is not requested again, with other credentials, headers or in any other way (the next strategy
is the adaptive ladder, #20).

The User-Agent is set on the guarded client (`build_client`), so it is on every request, the
permission resources and the redirects included.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from app.crawl.permissions import (
    SERVICE_NAME,
    TDM_HEADER,
    DomainPermission,
    SuppressionList,
    check_domain,
    crawler_user_agent,
    domain_of,
)
from app.db import utc_now
from app.http_client import (
    FetchSettings,
    FetchTimeoutError,
    GuardedClient,
    TooManyRedirectsError,
)

logger = logging.getLogger(__name__)

FetchStatus = Literal["fetched", "excluded", "not_crawled", "disallowed", "blocked", "too_large"]

# Markers of a challenge page (CAPTCHA or bot check) that a person must solve.
CAPTCHA_MARKERS = (
    "g-recaptcha",
    "h-captcha",
    "hcaptcha.com",
    "cf-turnstile",
    "challenges.cloudflare.com",
    "px-captcha",
)
CAPTCHA_HEADERS = {"cf-mitigated": "challenge"}
_SCAN_CHARS = 200_000
BINARY_TYPES = ("application/pdf", "image/", "audio/", "video/", "application/octet-stream")


def build_client(
    contact_url: str | None, settings: FetchSettings | None = None, **kwargs: Any
) -> GuardedClient:
    """A guarded client whose every request carries the crawler's User-Agent."""
    return GuardedClient(
        settings, headers={"User-Agent": crawler_user_agent(contact_url)}, **kwargs
    )


@dataclass
class FetchResult:
    status: FetchStatus
    url: str
    # The response when `status` is "fetched"; None otherwise (nothing of a refused page is kept).
    response: Any = None
    # With `too_large`: the size announced by the site, or the bytes read when it announced none.
    size: int | None = None
    # With `fetched`: the address answered after the redirects (equal to `url` without any).
    final_url: str | None = None


@dataclass
class BoundedResponse:
    """A response whose body was read with a size limit (`PermittedFetcher.fetch(max_bytes=...)`).

    `content` holds the bytes as the client decoded them (content encodings undone), never more
    than the limit.
    """

    status_code: int
    headers: Any
    content: bytes
    url: str

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


def is_challenge(response: Any) -> bool:
    """401, 403, or a page that asks a person to solve a CAPTCHA or a bot check."""
    if response.status_code in (401, 403):
        return True
    for header, value in CAPTCHA_HEADERS.items():
        if response.headers.get(header, "").lower() == value:
            return True
    if response.headers.get("content-type", "").startswith(BINARY_TYPES):
        return False
    text = response.text[:_SCAN_CHARS].lower()
    return any(marker in text for marker in CAPTCHA_MARKERS)


class PermittedFetcher:
    def __init__(
        self,
        client: GuardedClient,
        suppression: SuppressionList,
        record: Callable[[DomainPermission], None],
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._client = client
        self._suppression = suppression
        self._record = record
        self._now = now
        self._permissions: dict[str, DomainPermission] = {}

    def permission(self, url: str) -> DomainPermission:
        """The permission of the domain of `url`; checked and recorded on the first call only."""
        domain = domain_of(url)
        if domain not in self._permissions:
            permission = check_domain(self._client, url, self._suppression, self._now)
            self._permissions[domain] = permission
            self._record(permission)
        return self._permissions[domain]

    def _mark(self, permission: DomainPermission, decision: Literal["excluded", "blocked"]) -> None:
        permission.decision = decision
        permission.checked_at = self._now()
        if decision == "excluded":
            permission.tdm_reservation = True
        self._record(permission)

    def _get(self, url: str, timeout: float, max_bytes: int | None) -> tuple[Any, int | None]:
        """The response, and the size when it exceeds `max_bytes` (the body is then not kept)."""
        if max_bytes is None:
            return self._client.get(url, timeout=timeout, follow_redirects=False), None
        with self._client.stream(url, timeout=timeout, follow_redirects=False) as response:
            announced = response.headers.get("content-length", "")
            if announced.isdigit() and int(announced) > max_bytes:
                return response, int(announced)  # the body is never read
            if self._client.redirect_target(url, response) is not None:
                return response, None  # a redirect has no body worth reading
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > max_bytes:  # Content-Length absent or wrong: stop reading here
                    return response, len(body)
            return BoundedResponse(response.status_code, response.headers, bytes(body), url), None

    def fetch(self, url: str, max_bytes: int | None = None) -> FetchResult:
        """Fetch `url`, following redirects here, one hop at a time.

        With `max_bytes`, the body is read while streaming and never beyond that limit: a larger
        body gives `too_large` (with its size) and the rest is not downloaded.

        The permissions of each target's domain (and its robots.txt rules for the path) are
        checked before the target is requested, so no page of an excluded domain is ever
        requested. The redirect cap and the total deadline are the client's settings.
        """
        settings = self._client.settings
        deadline = time.monotonic() + settings.timeout_seconds
        current = url
        for _hop in range(settings.max_redirects + 1):
            permission = self.permission(current)
            if permission.decision == "excluded":
                return FetchResult("excluded", url)
            if permission.decision == "blocked":
                return FetchResult("blocked", url)
            if permission.decision != "allowed":
                return FetchResult("not_crawled", url)
            if permission.robots is not None and not permission.robots.can_fetch(
                current, SERVICE_NAME
            ):
                return FetchResult("disallowed", url)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FetchTimeoutError(
                    f"The website did not respond within {settings.timeout_seconds:g} seconds."
                )
            response, oversize = self._get(current, remaining, max_bytes)
            if response.headers.get(TDM_HEADER, "").strip() == "1":
                logger.info(
                    "Page of %s carries a TDM reservation; domain excluded", permission.domain
                )
                self._mark(permission, "excluded")
                return FetchResult("excluded", url)
            if oversize is not None:
                return FetchResult("too_large", url, size=oversize)
            # A body-bounded response was read to the end: it is not a redirect.
            bounded = isinstance(response, BoundedResponse)
            target = None if bounded else self._client.redirect_target(current, response)
            if target is not None:
                current = target
                continue
            if is_challenge(response):
                logger.info(
                    "Domain %s blocked the crawler (%s)", permission.domain, response.status_code
                )
                self._mark(permission, "blocked")
                return FetchResult("blocked", url)
            return FetchResult("fetched", url, response, final_url=current)
        raise TooManyRedirectsError(
            f"The website redirected more than {settings.max_redirects} times."
        )
