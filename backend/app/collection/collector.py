"""Collects the key pages and linked PDF reports of one supplier website (spec F2).

Every request goes through `PermittedFetcher` (permissions of #17, guarded client of #15), under
the per-domain rate limit. What is collected is handed to `store`, the single source-storage
function; this module never writes a source itself.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit

from app.collection.html_text import parse_html
from app.collection.identity import name_appears
from app.collection.limiter import DomainRateLimiter
from app.collection.pages import PAGE_KINDS, classify
from app.collection.pdf import extract_pdf
from app.collection.settings import CollectionSettings
from app.collection.sitemap import parse_sitemap
from app.collection.source_store import SourceRecord
from app.crawl import PermittedFetcher
from app.crawl.permissions import domain_of
from app.db import utc_now
from app.http_client import NETWORK_ERRORS, FetchError, FetchTimeoutError

logger = logging.getLogger(__name__)

RETRYABLE: tuple[type[Exception], ...] = (*NETWORK_ERRORS, FetchTimeoutError)
PER_KIND = 2  # pages kept per kind (for example two sustainability pages)
RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_BACKOFF_SECONDS = 60.0
HTML_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
SKIPPED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".mp4", ".mp3", ".css", ".js",
    ".xml", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)  # fmt: skip


@dataclass
class CollectionResult:
    sources: list[SourceRecord] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # URLs not collected, with the reason logged
    identity_to_verify: bool = False


def _host(url: str) -> str:
    host = domain_of(url)
    return host.removeprefix("www.")


def _content_type(response: Any) -> str:
    raw = str(response.headers.get("content-type", ""))
    return raw.split(";", 1)[0].strip().lower()


class Collector:
    def __init__(
        self,
        fetcher: PermittedFetcher,
        settings: CollectionSettings,
        store: Callable[[SourceRecord], None],
        limiter: DomainRateLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = utc_now,
        check_stop: Callable[[], None] = lambda: None,
    ) -> None:
        self._fetcher = fetcher
        self._settings = settings
        self._store = store
        self._limiter = limiter or DomainRateLimiter(settings.min_delay_seconds)
        self._sleep = sleep
        self._now = now
        self._check_stop = check_stop
        self.result = CollectionResult()

    # -- fetching ---------------------------------------------------------------------------

    def _fetch(self, url: str, max_bytes: int) -> Any:
        """The response of `url`, or None (refused, too large, not found, or failing after the
        retries). Waits for the domain's slot before each request; backs off between retries."""
        attempts = self._settings.retries + 1
        for attempt in range(attempts):
            self._check_stop()
            try:
                with self._limiter.slot(domain_of(url)):
                    result = self._fetcher.fetch(url, max_bytes=max_bytes)
            except RETRYABLE as error:
                logger.warning("Fetch of %s failed (%s)", url, type(error).__name__)
                result = None
            except FetchError as error:  # refused by the guard: not retried
                logger.info("Fetch of %s refused (%s)", url, type(error).__name__)
                return self._skip(url)
            delay = self._settings.backoff_seconds * 2**attempt
            if result is not None:
                if result.status == "too_large":
                    logger.warning("Skipped %s: %s bytes exceeds %s", url, result.size, max_bytes)
                    return self._skip(url)
                if result.status != "fetched":
                    logger.info("Not fetched: %s (%s)", url, result.status)
                    return self._skip(url)
                status = result.response.status_code
                if status not in RETRY_STATUSES:
                    if status >= 400:
                        logger.info("Not collected: %s answered %s", url, status)
                        return self._skip(url)
                    return result.response
                retry_after = result.response.headers.get("retry-after", "")
                if retry_after.isdigit():
                    delay = max(delay, float(retry_after))
            if attempt + 1 < attempts:
                self._sleep(min(delay, MAX_BACKOFF_SECONDS))
        logger.warning("Gave up on %s after %d attempts", url, attempts)
        return self._skip(url)

    def _skip(self, url: str) -> Any:
        """Record a URL as not collected; returns None, for `return self._skip(url)`."""
        self.result.skipped.append(url)
        return None

    # -- discovery --------------------------------------------------------------------------

    def _sitemap_urls(self, home: str) -> list[str]:
        settings = self._settings
        queue = [urljoin(home, "/sitemap.xml")]
        permission = self._fetcher.permission(home)
        robots = permission.robots
        if robots is not None:
            queue = [*(s for s in robots.sitemaps if _host(s) == _host(home)), *queue]
        seen: set[str] = set()
        urls: list[str] = []
        while queue and len(seen) < settings.max_sitemaps:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            response = self._fetch(url, settings.max_sitemap_bytes)
            if response is None:
                continue
            sitemap = parse_sitemap(
                response.content,
                settings.max_sitemap_bytes,
                settings.max_sitemap_urls,
            )
            urls.extend(sitemap.urls[: settings.max_sitemap_urls - len(urls)])
            queue.extend(c for c in sitemap.children if _host(c) == _host(home))
        return urls

    def _absolute(self, base: str, href: str, home: str) -> str | None:
        try:
            url, _fragment = urldefrag(urljoin(base, href.strip()))
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or _host(url) != _host(home):
                return None
        except ValueError:
            return None
        return url

    # -- the run ----------------------------------------------------------------------------

    def collect(self, website: str, legal_name: str) -> CollectionResult:
        settings = self._settings
        parts = urlsplit(website)
        home = f"{parts.scheme}://{parts.netloc}/"
        collected: list[str] = []  # texts of the stored sources
        stored_urls: set[str] = set()
        pdf_links: list[str] = []
        ranked: dict[str, list[str]] = {kind: [] for kind in PAGE_KINDS}

        def add_candidate(url: str, anchor: str = "") -> None:
            kind = classify(url, anchor)
            if url.lower().split("?", 1)[0].endswith(".pdf"):
                if url not in pdf_links:
                    pdf_links.append(url)
            elif kind and kind != "home" and url not in ranked[kind]:
                if not urlsplit(url).path.lower().endswith(SKIPPED_EXTENSIONS):
                    ranked[kind].append(url)

        def take_page(url: str) -> list[tuple[str, str]]:
            """Fetch and store one page; the links found on it."""
            response = self._fetch(url, settings.max_page_bytes)
            if response is None:
                return []
            content_type = _content_type(response)
            if content_type and content_type not in HTML_TYPES:
                logger.info("Not a page: %s is %s", url, content_type)
                self._skip(url)
                return []
            page = parse_html(response.content, response.headers.get("content-type", ""))
            if not page.text:
                logger.info("Empty content: %s", url)
                self._skip(url)
                return page.links
            self._keep(SourceRecord(url, self._now(), content_type or "text/html", page.text))
            collected.append(page.text)
            stored_urls.add(url)
            return page.links

        # The home page, its links, then the sitemaps.
        links = take_page(home)
        for href, anchor in links:
            url = self._absolute(home, href, home)
            if url:
                add_candidate(url, anchor)
        for url in self._sitemap_urls(home):
            checked = self._absolute(home, url, home)
            if checked:
                add_candidate(checked)

        budget = settings.max_pages - len(stored_urls)
        chosen: list[str] = []
        for rank in range(PER_KIND):  # first one of each kind, then the second ones
            for kind in PAGE_KINDS[1:]:
                if rank < len(ranked[kind]) and ranked[kind][rank] != home:
                    chosen.append(ranked[kind][rank])
        for url in chosen[: max(budget, 0)]:
            for href, _anchor in take_page(url):
                absolute = self._absolute(url, href, home)
                if absolute and absolute.lower().split("?", 1)[0].endswith(".pdf"):
                    add_candidate(absolute)

        for url in pdf_links[: settings.max_pdfs]:
            text = self._take_pdf(url)
            if text:
                collected.append(text)

        # Flag only when something was collected: with nothing, there is nothing to compare.
        self.result.identity_to_verify = bool(collected) and not name_appears(legal_name, collected)
        return self.result

    def _take_pdf(self, url: str) -> str | None:
        response = self._fetch(url, self._settings.max_pdf_bytes)
        if response is None:
            return None
        content = response.content
        if _content_type(response) != "application/pdf" and not content.startswith(b"%PDF-"):
            logger.info("Not a PDF: %s", url)
            self._skip(url)
            return None
        pdf = extract_pdf(content, self._settings.max_pdf_pages)
        if not pdf.text:
            logger.info("Empty content: %s", url)
            self._skip(url)
            return None
        self._keep(SourceRecord(url, self._now(), "application/pdf", pdf.text, pdf.author))
        return pdf.text

    def _keep(self, record: SourceRecord) -> None:
        self._store(record)
        self.result.sources.append(record)
