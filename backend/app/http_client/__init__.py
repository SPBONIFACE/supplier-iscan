"""The HTTP client module: the only place that opens outgoing HTTP connections to supplier sites.

Every other module fetches through `GuardedClient` (enforced by tests/test_outbound_http_policy.py).
"""

from app.http_client.client import NETWORK_ERRORS, FetchSettings, GuardedClient, load_fetch_settings
from app.http_client.errors import (
    BlockedAddressError,
    DnsResolutionError,
    FetchError,
    FetchTimeoutError,
    InvalidUrlError,
    TooManyRedirectsError,
)
from app.http_client.url_guard import is_public_address, normalise_url
from app.http_client.website_check import WebsiteCheckResult, check_website

__all__ = [
    "NETWORK_ERRORS",
    "BlockedAddressError",
    "DnsResolutionError",
    "FetchError",
    "FetchSettings",
    "FetchTimeoutError",
    "GuardedClient",
    "InvalidUrlError",
    "TooManyRedirectsError",
    "WebsiteCheckResult",
    "check_website",
    "is_public_address",
    "load_fetch_settings",
    "normalise_url",
]
