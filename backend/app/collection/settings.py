"""Collection limits, read from environment variables (all optional; local defaults).

- `COLLECT_MAX_PAGES` (12): pages fetched per run, the home page included.
- `COLLECT_MAX_PDFS` (5): linked PDF reports fetched per run.
- `COLLECT_MAX_PAGE_BYTES` (2 MB): a page body is never read beyond this.
- `COLLECT_MAX_PDF_BYTES` (20 MB): a PDF is never downloaded beyond this.
- `COLLECT_MAX_PDF_PAGES` (200): pages of a PDF whose text is read.
- `COLLECT_MIN_DELAY_SECONDS` (1): minimum delay between two requests to one domain.
- `COLLECT_RETRIES` (2) and `COLLECT_BACKOFF_SECONDS` (1): retries of a failed fetch, with the
  delay doubling each time.
- `COLLECT_MAX_SITEMAPS` (5), `COLLECT_MAX_SITEMAP_URLS` (2000), `COLLECT_MAX_SITEMAP_BYTES`
  (2 MB, after decompression): caps on the (hostile) sitemaps.
The request timeout is `FETCH_TIMEOUT_SECONDS` of the HTTP client (#15).
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

from app.config import ConfigurationError


@dataclass(frozen=True)
class CollectionSettings:
    max_pages: int = 12
    max_pdfs: int = 5
    max_page_bytes: int = 2_000_000
    max_pdf_bytes: int = 20_000_000
    max_pdf_pages: int = 200
    min_delay_seconds: float = 1.0
    retries: int = 2
    backoff_seconds: float = 1.0
    max_sitemaps: int = 5
    max_sitemap_urls: int = 2000
    max_sitemap_bytes: int = 2_000_000


def _number(env: Mapping[str, str], name: str, default: float, *, whole: bool) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw) if whole else float(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a number") from error
    if value < 0 or value > 10_000_000_000:
        raise ConfigurationError(f"{name} is out of range")
    return value


def load_collection_settings(environ: Mapping[str, str] | None = None) -> CollectionSettings:
    env = os.environ if environ is None else environ
    d = CollectionSettings()

    def whole(name: str, default: int) -> int:
        return int(_number(env, name, default, whole=True))

    return CollectionSettings(
        max_pages=whole("COLLECT_MAX_PAGES", d.max_pages),
        max_pdfs=whole("COLLECT_MAX_PDFS", d.max_pdfs),
        max_page_bytes=whole("COLLECT_MAX_PAGE_BYTES", d.max_page_bytes),
        max_pdf_bytes=whole("COLLECT_MAX_PDF_BYTES", d.max_pdf_bytes),
        max_pdf_pages=whole("COLLECT_MAX_PDF_PAGES", d.max_pdf_pages),
        min_delay_seconds=_number(
            env, "COLLECT_MIN_DELAY_SECONDS", d.min_delay_seconds, whole=False
        ),
        retries=whole("COLLECT_RETRIES", d.retries),
        backoff_seconds=_number(env, "COLLECT_BACKOFF_SECONDS", d.backoff_seconds, whole=False),
        max_sitemaps=whole("COLLECT_MAX_SITEMAPS", d.max_sitemaps),
        max_sitemap_urls=whole("COLLECT_MAX_SITEMAP_URLS", d.max_sitemap_urls),
        max_sitemap_bytes=whole("COLLECT_MAX_SITEMAP_BYTES", d.max_sitemap_bytes),
    )
