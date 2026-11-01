"""Crawl permissions and crawler identity (spec F2; #17).

`PermittedFetcher` is the only way the collection stages (#18, #20) fetch a supplier's pages: it
checks the site owner's signals first, records them, and refuses what they exclude.
"""

from app.crawl.fetcher import FetchResult, PermittedFetcher, build_client
from app.crawl.permissions import (
    AI_CRAWLERS,
    EXCLUSION_MESSAGE,
    DomainPermission,
    EmptySuppressionList,
    SuppressionList,
    check_domain,
    crawler_user_agent,
)
from app.crawl.store import DatabaseSuppressionList, excluded_sources, record_permission

__all__ = [
    "AI_CRAWLERS",
    "EXCLUSION_MESSAGE",
    "DatabaseSuppressionList",
    "DomainPermission",
    "EmptySuppressionList",
    "FetchResult",
    "PermittedFetcher",
    "SuppressionList",
    "build_client",
    "check_domain",
    "crawler_user_agent",
    "excluded_sources",
    "record_permission",
]
