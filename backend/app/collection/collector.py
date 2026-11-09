"""Collects the key pages and linked PDF reports of one supplier website (spec F2).

Every request goes through `PermittedFetcher` (permissions of #17, guarded client of #15), under
the per-domain rate limit. What is collected is handed to `store`, the single source-storage
function; this module never writes a source itself.
"""

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

from app.collection.budget import DomainLimitReached, RequestLimitReached
from app.collection.failures import (
    DOMAIN_CAP_MESSAGE,
    REQUEST_CAP_MESSAGE,
    Failure,
    Kind,
    RetrievalFailed,
    Strategy,
    make_failure,
)
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
# The lacking page kinds in (empty when the website gave every kind: independent sources are then
# asked for), the addresses the retrieval provider cited (best first) out.
RetrieveFn = Callable[[list[str]], list[str]]


class RetrievedAddresses(list[str]):
    """The merged addresses of a retrieval step made of several requests. `failures` are the
    requests that failed (each recorded like a failed retrieval, the others still ran);
    `budget_exhausted` is set when the run's cost budget stopped the remaining requests."""

    def __init__(self, urls: list[str]) -> None:
        super().__init__(urls)
        self.failures: list[RetrievalFailed] = []
        self.budget_exhausted = False


HTML_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
SKIPPED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".mp4", ".mp3", ".css", ".js",
    ".xml", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)  # fmt: skip
PER_PAGE_LINKED_PDFS = 2  # PDFs followed from one retrieved third-party page
FINANCIAL_WORDS = (
    "annual report", "annual accounts", "financial statements", "accounts", "jahresabschluss",
    "geschäftsbericht", "geschaeftsbericht", "bilanz", "comptes annuels", "rapport annuel",
    "bilan",
)  # fmt: skip
FINANCIAL_WORDS_HYPHENATED = tuple(w.replace(" ", "-") for w in FINANCIAL_WORDS if " " in w)
FILED_ACCOUNTS_NAME = re.compile(r"(?<![a-z])ea[-_]?\d{4}")  # a file name such as EA2025.pdf


@dataclass
class CollectionResult:
    sources: list[SourceRecord] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # URLs not collected, with the reason logged
    failures: list[Failure] = field(default_factory=list)  # the failure log (spec F2)
    identity_to_verify: bool = False
    attempts: int = 0  # requests made for content, retries included (never above the cap)


def _host(url: str) -> str:
    host = domain_of(url)
    return host.removeprefix("www.")


def _is_pdf(url: str) -> bool:
    return url.lower().split("?", 1)[0].endswith(".pdf")


def _is_financial(url: str, anchor: str) -> bool:
    """The address or the anchor text names a financial document (English, French, German)."""
    address = unquote(url).lower()
    text = f"{address} {anchor.lower()}"
    if any(word in text for word in (*FINANCIAL_WORDS, *FINANCIAL_WORDS_HYPHENATED)):
        return True
    name = urlsplit(address).path.rsplit("/", 1)[-1]
    return bool(FILED_ACCOUNTS_NAME.search(name))


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
        self._strategy: Strategy = "website"
        self._cap_logged = False
        self._final_url = ""  # address answered by the last successful `_fetch`
        self._requests_exhausted = False  # the ceiling on all outbound requests was reached
        self._domains_refused: set[str] = set()
        self._website_texts: list[str] = []
        self._kinds_found: set[str] = set()
        self._website_host = ""
        self._linked_pdfs = 0  # PDFs followed from retrieved third-party pages in this run

    # -- failures ---------------------------------------------------------------------------

    def _fail(
        self, url: str | None, kind: Kind, status: int | None = None, message: str | None = None
    ) -> None:
        failure = make_failure(url, self._strategy, kind, status, message)
        logger.info(
            "Collection failure: url=%s strategy=%s kind=%s next=%s",
            url,
            failure.strategy,
            kind,
            failure.next_strategy,
        )
        self.result.failures.append(failure)

    # -- fetching ---------------------------------------------------------------------------

    def _fetch(self, url: str, max_bytes: int) -> Any:
        """The response of `url`, or None (refused, too large, not found, or failing after the
        retries). Waits for the domain's slot before each request; backs off between retries.
        Every request counts as an attempt; none is made beyond the cap of the run."""
        attempts = self._settings.retries + 1
        kind: Kind = "unreachable"
        status = None
        for attempt in range(attempts):
            self._check_stop()
            if self._requests_exhausted:
                return self._skip(url)
            if self.result.attempts >= self._settings.max_attempts:
                if not self._cap_logged:
                    self._cap_logged = True
                    self._fail(None, "attempt_cap")
                return self._skip(url)
            self.result.attempts += 1
            try:
                with self._limiter.slot(domain_of(url)):
                    result = self._fetcher.fetch(url, max_bytes=max_bytes)
            except RETRYABLE as error:
                logger.warning("Fetch of %s failed (%s)", url, type(error).__name__)
                kind = "timeout" if isinstance(error, FetchTimeoutError) else "unreachable"
                result = None
            except RequestLimitReached:
                self._request_ceiling()
                return self._skip(url)
            except DomainLimitReached as error:
                if error.domain not in self._domains_refused:
                    self._domains_refused.add(error.domain)
                    self._fail(url, "attempt_cap", message=DOMAIN_CAP_MESSAGE)
                return self._skip(url)
            except FetchError as error:  # refused by the guard: not retried
                logger.info("Fetch of %s refused (%s)", url, type(error).__name__)
                return self._skip(url, "refused")
            delay = self._settings.backoff_seconds * 2**attempt
            if result is not None:
                if result.status == "too_large":
                    logger.warning("Skipped %s: %s bytes exceeds %s", url, result.size, max_bytes)
                    return self._skip(url, "too_large")
                if result.status != "fetched":
                    logger.info("Not fetched: %s (%s)", url, result.status)
                    return self._skip(url, "blocked_by_robots")
                status = result.response.status_code
                if status not in RETRY_STATUSES:
                    if status >= 400:
                        logger.info("Not collected: %s answered %s", url, status)
                        return self._skip(url, "http_error", status)
                    self._final_url = result.final_url or url
                    return result.response
                kind = "http_error"
                retry_after = result.response.headers.get("retry-after", "")
                if retry_after.isdigit():
                    delay = max(delay, float(retry_after))
            if attempt + 1 < attempts:
                self._sleep(min(delay, MAX_BACKOFF_SECONDS))
        logger.warning("Gave up on %s after %d attempts", url, attempts)
        return self._skip(url, kind, status)

    def _request_ceiling(self) -> None:
        """The ceiling on all requests was reached: logged once, nothing more is requested."""
        if not self._requests_exhausted:
            self._requests_exhausted = True
            logger.warning("Collection reached its limit of requests; going on with what it has")
            self._fail(None, "attempt_cap", message=REQUEST_CAP_MESSAGE)

    def _skip(self, url: str, kind: Kind | None = None, status: int | None = None) -> Any:
        """Record a URL as not collected (with the failure when it has a kind); returns None,
        for `return self._skip(url)`."""
        self.result.skipped.append(url)
        if kind is not None:
            self._fail(url, kind, status)
        return None

    # -- discovery --------------------------------------------------------------------------

    def _sitemap_urls(self, home: str) -> list[str]:
        settings = self._settings
        queue = [urljoin(home, "/sitemap.xml")]
        try:
            permission = self._fetcher.permission(home)
        except RequestLimitReached:
            self._request_ceiling()
            return []
        except DomainLimitReached:
            return []
        robots = permission.robots
        if robots is not None:
            queue = [*(s for s in robots.sitemaps if _host(s) == _host(home)), *queue]
        seen: set[str] = set()
        urls: list[str] = []
        self._strategy = "sitemap"
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

    def _link(self, base: str, href: str, home: str) -> str | None:
        """A link of a page of the website: an address of the website, or a PDF wherever it is
        hosted (a PDF linked from the supplier's website is its own claim, owner decision 27 Oct
        2026; it is still fetched through the permission checks and the ceilings of the run)."""
        url = self._absolute(base, href, home)
        if url:
            return url
        try:
            other, _fragment = urldefrag(urljoin(base, href.strip()))
            if urlsplit(other).scheme in ("http", "https") and _is_pdf(other):
                return other
        except ValueError:
            pass
        return None

    # -- the run ----------------------------------------------------------------------------

    def collect(
        self, website: str | None, legal_name: str, retrieve: RetrieveFn | None = None
    ) -> CollectionResult:
        """The ladder: the website (home page, its links, the sitemaps), then the retrieval
        provider's addresses (`retrieve`), all under one cap of attempts. `website` is None when
        the identity has none."""
        if website:
            self._website_host = _host(website)
            self._crawl_website(website)
        website_texts = list(self._website_texts)
        website_sources = len(self.result.sources)
        if retrieve is not None and not self._requests_exhausted:
            self._retrieve(retrieve)
        # Identity (spec F1, owner decision D-065). Nothing found at all: the run ends
        # insufficient_sources and is not flagged. The website gave no source but others were
        # found: flagged, nothing has confirmed the identity. Otherwise, flagged when the name is
        # on none of the website's texts.
        if not self.result.sources:
            self.result.identity_to_verify = False
        elif website_sources == 0:
            self.result.identity_to_verify = True
        else:
            self.result.identity_to_verify = not name_appears(legal_name, website_texts)
        return self.result

    def _retrieve(self, retrieve: RetrieveFn) -> None:
        """Addresses from the retrieval provider, fetched and stored like any source. Only the
        addresses are used: the provider's answer text and snippets are never stored."""
        self._strategy = "retrieval"
        lacking = [kind for kind in PAGE_KINDS if kind not in self._kinds_found]
        # Also when nothing is lacking: the provider is then asked for independent sources.
        self._check_stop()
        try:
            urls = retrieve(lacking)
        except RetrievalFailed as error:
            self._fail(None, error.kind, message=error.message)
            return
        for failed in getattr(urls, "failures", []):
            self._fail(None, failed.kind, message=failed.message)
        crawl_full = len(self.result.sources) >= self._settings.crawl_pages
        stored = {record.url for record in self.result.sources}
        for url in self._independent_first(urls)[: self._settings.max_retrieval_urls]:
            if url in stored or urlsplit(url).scheme not in ("http", "https"):
                if url not in stored:
                    self._skip(url, "refused")
                continue
            if crawl_full and not self._third_party(url):
                # The reserved slots are for addresses outside the supplier's website.
                self._skip(url, "refused")
                continue
            if url.lower().split("?", 1)[0].endswith(".pdf"):
                self._take_pdf(url)
            else:
                links = self._take_page(url)
                if links and self._third_party(self._final_url or url):
                    self._follow_linked_pdfs(self._final_url or url, links)

    def _third_party(self, url: str) -> bool:
        own = self._website_host
        host = _host(url)
        return not (own and (host == own or host.endswith("." + own)))

    def _follow_linked_pdfs(self, page: str, links: list[tuple[str, str]]) -> None:
        """The PDFs a retrieved third-party page links and hosts itself, financial documents
        first (at most 2 per page and `max_linked_pdfs` per run). Each is stored as linked from
        the page; its source type is decided by its own address."""
        host = _host(page)
        candidates: list[tuple[str, str]] = []
        for href, anchor in links:
            try:
                url, _fragment = urldefrag(urljoin(page, href.strip()))
                ok = urlsplit(url).scheme in ("http", "https") and _host(url) == host
            except ValueError:
                continue
            if ok and _is_pdf(url) and all(url != c[0] for c in candidates):
                candidates.append((url, anchor))
        candidates.sort(key=lambda c: not _is_financial(*c))  # stable: page order inside a rank
        taken = 0
        for url, _anchor in candidates:
            if taken >= PER_PAGE_LINKED_PDFS or self._linked_pdfs >= self._settings.max_linked_pdfs:
                break
            if self._requests_exhausted or self._already_kept(url):
                continue
            if self._take_pdf(url, page) is not None:
                taken += 1
                self._linked_pdfs += 1

    def _independent_first(self, urls: list[str]) -> list[str]:
        """The addresses with at most one on the supplier's own domain when the website crawl
        already produced sources; the others keep their order and take the remaining slots."""
        own = self._website_host
        if not own or not any(_host(r.url) == own for r in self.result.sources):
            return urls
        kept: list[str] = []
        own_taken = 0
        for url in urls:
            try:
                host = _host(url)
            except ValueError:
                host = ""
            if host == own or host.endswith("." + own):
                own_taken += 1
                if own_taken > 1:
                    continue
            kept.append(url)
        return kept

    def _crawl_website(self, website: str) -> None:
        settings = self._settings
        parts = urlsplit(website)
        home = f"{parts.scheme}://{parts.netloc}/"
        pdf_links: list[str] = []
        linked_from: dict[str, str] = {}  # a PDF's address -> the page that linked to it
        ranked: dict[str, list[str]] = {kind: [] for kind in PAGE_KINDS}
        self._strategy = "website"

        def add_candidate(url: str, anchor: str = "", page: str | None = None) -> None:
            kind = classify(url, anchor)
            if _is_pdf(url):
                if url not in pdf_links:
                    pdf_links.append(url)
                if page:
                    linked_from.setdefault(url, page)
            elif kind and kind != "home" and url not in ranked[kind]:
                if not urlsplit(url).path.lower().endswith(SKIPPED_EXTENSIONS):
                    ranked[kind].append(url)

        def take_page(url: str) -> list[tuple[str, str]]:
            return self._take_page(url) or []

        # The home page, its links, then the sitemaps.
        links = take_page(home)
        for href, anchor in links:
            url = self._link(home, href, home)
            if url:
                add_candidate(url, anchor, home)
        for url in self._sitemap_urls(home):
            checked = self._absolute(home, url, home)
            if checked:
                add_candidate(checked)
        self._strategy = "website"

        budget = settings.crawl_pages - len(self.result.sources)
        chosen: list[str] = []
        for rank in range(PER_KIND):  # first one of each kind, then the second ones
            for kind in PAGE_KINDS[1:]:
                if rank < len(ranked[kind]) and ranked[kind][rank] != home:
                    chosen.append(ranked[kind][rank])
        for url in chosen[: max(budget, 0)]:
            for href, _anchor in take_page(url):
                absolute = self._link(url, href, home)
                if absolute and _is_pdf(absolute):
                    add_candidate(absolute, page=url)

        for url in pdf_links[
            : min(settings.max_pdfs, max(settings.crawl_pages - len(self.result.sources), 0))
        ]:
            self._take_pdf(url, linked_from.get(url))

    def _take_page(self, url: str) -> list[tuple[str, str]] | None:
        """Fetch and store one page; the links found on it, or None when it could not be read."""
        response = self._fetch(url, self._settings.max_page_bytes)
        if response is None:
            return None
        final = self._final_url  # after redirects: the source is what was answered there
        content_type = _content_type(response)
        if content_type and content_type not in HTML_TYPES:
            logger.info("Not a page: %s is %s", url, content_type)
            self._skip(url, "not_a_page")
            return None
        page = parse_html(response.content, response.headers.get("content-type", ""))
        if not page.text:
            logger.info("Empty content: %s", url)
            self._skip(url, "empty_content")
            return page.links
        if final != url and self._already_kept(final):
            return page.links
        self._keep(SourceRecord(final, self._now(), content_type or "text/html", page.text))
        return page.links

    def _take_pdf(self, url: str, linked_from: str | None = None) -> str | None:
        response = self._fetch(url, self._settings.max_pdf_bytes)
        if response is None:
            return None
        final = self._final_url
        content = response.content
        if _content_type(response) != "application/pdf" and not content.startswith(b"%PDF-"):
            logger.info("Not a PDF: %s", url)
            self._skip(url, "not_a_page")
            return None
        pdf = extract_pdf(content, self._settings.max_pdf_pages)
        if not pdf.text:
            logger.info("Empty content: %s", url)
            self._skip(url, "empty_content")
            return None
        if final != url and self._already_kept(final):
            return pdf.text
        # A PDF linked from the supplier's page stays the supplier's own claim wherever it is
        # hosted (owner decision, 27 Oct 2026), but only for the address that was linked: when
        # the link redirects to another host, the text is that host's, so the link is dropped
        # and the final address alone decides the source type.
        if linked_from and _host(final) != _host(url):
            linked_from = None
        self._keep(
            SourceRecord(final, self._now(), "application/pdf", pdf.text, pdf.author, linked_from)
        )
        return pdf.text

    def _already_kept(self, url: str) -> bool:
        return any(record.url == url for record in self.result.sources)

    def _keep(self, record: SourceRecord) -> None:
        self._store(record)
        self.result.sources.append(record)
        if self._strategy != "retrieval":
            self._website_texts.append(record.text)
        kind = classify(record.url)
        if kind:
            self._kinds_found.add(kind)
