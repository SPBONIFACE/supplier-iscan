"""The check of a domain's crawl-permission signals (spec F2, Robustness cases).

Requests made for a domain: `/robots.txt` and `/.well-known/tdmrep.json`, nothing else. A domain
on the suppression list is not contacted at all. The decision is `excluded` (the site owner's
request: a TDM reservation, a robots.txt block of an AI crawler, the suppression list),
`not_crawled` (robots.txt or `tdmrep.json` unreachable or refused: owner decision Q16, the domain
is not crawled in this run) or `allowed`.

Each robots.txt and tdmrep.json status is classified the same way: 2xx is read, 401 and 403 mean
blocked, any other 4xx means absent, 5xx, 429, a timeout and a network failure mean unreachable.
"""

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from urllib.parse import urlsplit

from protego import Protego

from app.config import ConfigurationError
from app.db import utc_now
from app.http_client import NETWORK_ERRORS, FetchError, GuardedClient

logger = logging.getLogger(__name__)

SERVICE_NAME = "SupplierIScan"
SERVICE_VERSION = "1.0"
# Product tokens of AI crawlers: a robots.txt group naming one that disallows the whole site is a
# reservation of text and data mining (spec F2).
AI_CRAWLERS = ("GPTBot", "ClaudeBot", "Google-Extended", "CCBot", "PerplexityBot")
EXCLUSION_MESSAGE = "Source excluded at the site owner's request."
TDM_HEADER = "tdm-reservation"

RobotsResult = Literal["not_checked", "found", "missing", "ai_blocked", "blocked", "unreachable"]
Decision = Literal["allowed", "excluded", "not_crawled", "blocked"]
_Fetched = Literal["ok", "absent", "blocked", "unreachable"]


class SuppressionList(Protocol):
    """The domain entries of the suppression list. #46 administers it."""

    def is_suppressed(self, domain: str) -> bool: ...


class EmptySuppressionList:
    """No entry: the default when no list is wired in."""

    def is_suppressed(self, domain: str) -> bool:
        return False


def crawler_user_agent(contact_url: str | None) -> str:
    """The User-Agent of every request: it names the service and links to the contact page."""
    if not contact_url:
        raise ConfigurationError(
            "CRAWLER_CONTACT_URL must be set before supplier sites are fetched"
        )
    return f"{SERVICE_NAME}/{SERVICE_VERSION} (+{contact_url})"


def domain_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("URL without a host")
    return host


@dataclass
class DomainPermission:
    domain: str
    robots_result: RobotsResult = "not_checked"
    tdm_reservation: bool = False
    suppression_hit: bool = False
    decision: Decision = "not_crawled"
    checked_at: datetime | None = None
    # Not stored: the parsed robots.txt, for the paths of an allowed domain.
    robots: Protego | None = None


def _classify(status: int) -> _Fetched:
    if 200 <= status < 300:
        return "ok"
    if status in (401, 403):
        return "blocked"
    if status == 429 or status >= 500:
        return "unreachable"
    return "absent"  # 404, 410 and the other client errors: nothing published


def _decode(content: bytes) -> str:
    """UTF-8 (RFC 9309), without a byte order mark and leading whitespace."""
    return content.decode("utf-8-sig", errors="replace").lstrip("\ufeff \t\r\n")


def _get(client: GuardedClient, url: str) -> tuple[_Fetched, str, bool]:
    """Fetch one permission resource: (outcome, text, tdm-reservation header is 1)."""
    try:
        response = client.get(url)
    except FetchError as error:
        logger.warning("Crawl permission resource unreachable (%s)", type(error).__name__)
        return "unreachable", "", False
    except NETWORK_ERRORS as error:
        logger.warning("Crawl permission resource unreachable (%s)", type(error).__name__)
        return "unreachable", "", False
    reserved = response.headers.get(TDM_HEADER, "").strip() == "1"
    outcome = _classify(response.status_code)
    return outcome, _decode(response.content) if outcome == "ok" else "", reserved


def _names_blocked_crawler(robots_text: str, robots: Protego, origin: str) -> bool:
    """True when a group names an AI crawler and disallows the whole site for it."""
    for crawler in AI_CRAWLERS:
        named = re.search(
            rf"^\s*user-agent\s*:\s*{re.escape(crawler)}\s*(#.*)?$",
            robots_text,
            re.IGNORECASE | re.MULTILINE,
        )
        if named and not robots.can_fetch(f"{origin}/", crawler):
            return True
    return False


def _tdmrep_reserves(text: str) -> bool:
    """Any entry of tdmrep.json that reserves rights excludes the domain (the safe reading).

    A document that is not valid JSON cannot be read as a reservation; it is logged and ignored.
    """
    try:
        entries = json.loads(text)
    except ValueError:
        logger.warning("tdmrep.json is not valid JSON; ignored")
        return False
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return False
    return any(
        isinstance(entry, dict) and str(entry.get(TDM_HEADER, "")).strip() == "1"
        for entry in entries
    )


def check_domain(
    client: GuardedClient,
    url: str,
    suppression: SuppressionList,
    now: Callable[[], datetime] = utc_now,
) -> DomainPermission:
    """Check the signals of the domain of `url` (its scheme and port are used for the requests)."""
    parts = urlsplit(url)
    domain = domain_of(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    permission = DomainPermission(domain=domain)

    def done(decision: Decision) -> DomainPermission:
        permission.decision = decision
        permission.checked_at = now()
        return permission

    if suppression.is_suppressed(domain):
        permission.suppression_hit = True
        return done("excluded")

    outcome, text, reserved = _get(client, f"{origin}/robots.txt")
    permission.tdm_reservation = reserved
    if outcome in ("blocked", "unreachable"):
        permission.robots_result = outcome
        logger.warning("robots.txt of %s: %s; domain not crawled in this run", domain, outcome)
        return done("excluded" if reserved else "not_crawled")
    if outcome == "absent":
        permission.robots_result = "missing"
    else:
        permission.robots_result = "found"
        permission.robots = Protego.parse(text)
        if _names_blocked_crawler(text, permission.robots, origin):
            permission.robots_result = "ai_blocked"

    outcome, text, reserved = _get(client, f"{origin}/.well-known/tdmrep.json")
    permission.tdm_reservation = permission.tdm_reservation or reserved
    if outcome == "ok" and _tdmrep_reserves(text):
        permission.tdm_reservation = True
    if permission.tdm_reservation or permission.robots_result == "ai_blocked":
        return done("excluded")
    if outcome in ("blocked", "unreachable"):
        logger.warning("tdmrep.json of %s: %s; domain not crawled in this run", domain, outcome)
        return done("not_crawled")
    return done("allowed")
