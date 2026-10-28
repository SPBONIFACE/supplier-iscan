"""Errors raised by the guarded HTTP client.

Every error carries a stable `code` (for the frontend to translate) and a plain-language English
`reason` that is safe to show to a member: it never contains a resolved IP address.
"""

from typing import Literal

__all__ = [
    "BlockedAddressError",
    "DnsResolutionError",
    "FetchError",
    "FetchErrorCode",
    "FetchTimeoutError",
    "InvalidUrlError",
    "TooManyRedirectsError",
]

FetchErrorCode = Literal[
    "invalid_url",
    "blocked_address",
    "dns_failure",
    "timeout",
    "too_many_redirects",
]


class FetchError(Exception):
    """Base class of the errors the guard and the guarded client raise themselves."""

    code: FetchErrorCode

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InvalidUrlError(FetchError, ValueError):
    """Empty, malformed, non-http(s) or credential-bearing URL (validation error)."""

    code = "invalid_url"


class BlockedAddressError(FetchError):
    """The target is, or resolves to, a private, loopback, link-local or other non-public IP."""

    code = "blocked_address"


class DnsResolutionError(FetchError):
    """The host name could not be resolved."""

    code = "dns_failure"


class FetchTimeoutError(FetchError):
    """The resolution or the whole fetch did not finish within the configured time."""

    code = "timeout"


class TooManyRedirectsError(FetchError):
    """The redirect chain is longer than the configured maximum."""

    code = "too_many_redirects"
