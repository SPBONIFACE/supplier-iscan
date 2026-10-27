"""Website check for the "None of these, enter the website" fallback (spec F1).

Accepts a URL or a bare domain, normalises it, and reports either "reachable" with the final domain
after redirects, or a plain-language reason, within the configured timeout. A bare domain is tried
with `https://` first, then with `http://` if the HTTPS connection cannot be made; an invalid
certificate is reported, never bypassed by falling back to `http://`.
"""

import logging
import ssl
import time
from dataclasses import dataclass
from typing import Literal

import httpx2

from app.http_client.client import GuardedClient
from app.http_client.errors import FetchError, FetchErrorCode
from app.http_client.url_guard import has_explicit_scheme, normalise_url

logger = logging.getLogger(__name__)

WebsiteCheckFailure = (
    FetchErrorCode
    | Literal["http_error", "connection_failed", "certificate_invalid", "invalid_response"]
)


@dataclass(frozen=True)
class WebsiteCheckResult:
    status: Literal["reachable", "unreachable"]
    # Set when reachable: host name of the final URL after redirects, ASCII (punycode) form.
    final_domain: str | None = None
    final_url: str | None = None
    # Set when unreachable: a stable code for the frontend and an English plain-language reason.
    failure: WebsiteCheckFailure | None = None
    reason: str | None = None
    http_status: int | None = None


def _unreachable(
    failure: WebsiteCheckFailure, reason: str, http_status: int | None = None
) -> WebsiteCheckResult:
    return WebsiteCheckResult(
        status="unreachable", failure=failure, reason=reason, http_status=http_status
    )


def check_website(raw: str, client: GuardedClient) -> WebsiteCheckResult:
    try:
        url = normalise_url(raw, assume_https=True)
    except FetchError as error:
        return _unreachable(error.code, error.reason)
    budget = client.settings.website_check_timeout_seconds
    deadline = time.monotonic() + budget
    result = _attempt(client, url, budget, budget)
    bare_domain = not has_explicit_scheme(raw)
    remaining = deadline - time.monotonic()
    if result.failure == "connection_failed" and bare_domain and remaining > 0:
        fallback = _attempt(client, url.copy_with(scheme="http"), remaining, budget)
        if fallback.status == "reachable":
            return fallback
    return result


def _attempt(
    client: GuardedClient, url: httpx2.URL, timeout: float, budget: float
) -> WebsiteCheckResult:
    timed_out = f"The website did not respond within {budget:g} seconds."
    try:
        with client.stream(url, timeout=timeout) as response:
            if response.status_code >= 400:
                phrase = response.reason_phrase or "error"
                return _unreachable(
                    "http_error",
                    f"The website answered with an error (HTTP {response.status_code} {phrase}).",
                    response.status_code,
                )
            final = response.url
            return WebsiteCheckResult(
                status="reachable",
                final_domain=final.raw_host.decode("ascii"),
                final_url=str(final),
            )
    except FetchError as error:
        reason = timed_out if error.code == "timeout" else error.reason
        return _unreachable(error.code, reason)
    except httpx2.TimeoutException:
        return _unreachable("timeout", timed_out)
    except httpx2.ConnectError as error:
        logger.info("Website check: connection to %s failed: %s", url.host, error)
        if _caused_by_tls(error):
            return _unreachable(
                "certificate_invalid",
                "The website's security certificate is not valid for this domain or has expired.",
            )
        return _unreachable(
            "connection_failed", "The website could not be reached: the connection failed."
        )
    except httpx2.HTTPError as error:
        logger.info("Website check: invalid response from %s: %s", url.host, error)
        return _unreachable("invalid_response", "The website sent a response that is not valid.")


def _caused_by_tls(error: BaseException) -> bool:
    cause: BaseException | None = error
    while cause is not None:
        if isinstance(cause, ssl.SSLError):
            return True
        cause = cause.__cause__ or cause.__context__
    return False
