"""The one HTTP client for fetches to supplier sites (crawling, PDFs, website check).

Every request goes through `GuardedTransport`. Redirects are followed here, one hop at a time:
each target is validated and vetted again, up to `FetchSettings.max_redirects`, and the whole
chain shares one deadline.

Configuration (environment, all optional):
- `FETCH_TIMEOUT_SECONDS` (default 10): time allowed for one fetch, redirects included.
- `FETCH_MAX_REDIRECTS` (default 5): redirects followed before giving up.
- `WEBSITE_CHECK_TIMEOUT_SECONDS` (default 10): time allowed for the website check.
"""

import os
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

import httpx2

from app.config import ConfigurationError
from app.http_client.errors import FetchTimeoutError, InvalidUrlError, TooManyRedirectsError
from app.http_client.transport import GuardedTransport, fetch_deadline
from app.http_client.url_guard import (
    Resolver,
    normalise_url,
    reject_userinfo,
    system_resolver,
    validate_url,
)

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_REDIRECTS = 5
_MAX_TIMEOUT_SECONDS = 300.0
_MAX_REDIRECTS_LIMIT = 20
MSG_INVALID_REDIRECT = "The website redirected to an invalid address."

__all__ = ["NETWORK_ERRORS", "FetchSettings", "GuardedClient", "load_fetch_settings"]

# What a fetch raises when the network fails (connection, TLS, read, timeout): for callers that
# treat it as "the site did not answer" without importing the HTTP library (#17).
NETWORK_ERRORS: tuple[type[Exception], ...] = (httpx2.HTTPError,)


@dataclass(frozen=True)
class FetchSettings:
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_redirects: int = DEFAULT_MAX_REDIRECTS
    website_check_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


def _seconds(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a number of seconds") from error
    if not 0 < value <= _MAX_TIMEOUT_SECONDS:
        raise ConfigurationError(f"{name} must be between 0 and {_MAX_TIMEOUT_SECONDS:g} seconds")
    return value


def _count(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a whole number") from error
    if not 0 <= value <= _MAX_REDIRECTS_LIMIT:
        raise ConfigurationError(f"{name} must be between 0 and {_MAX_REDIRECTS_LIMIT}")
    return value


def load_fetch_settings(environ: Mapping[str, str] | None = None) -> FetchSettings:
    env = os.environ if environ is None else environ
    return FetchSettings(
        timeout_seconds=_seconds(env, "FETCH_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        max_redirects=_count(env, "FETCH_MAX_REDIRECTS", DEFAULT_MAX_REDIRECTS),
        website_check_timeout_seconds=_seconds(
            env, "WEBSITE_CHECK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS
        ),
    )


_LOCATION = "app.http_client.redirect_location"


def _take_redirect_location(response: httpx2.Response) -> None:
    """Response hook: take the `Location` of a redirect away from httpx2 before it parses it.

    httpx2 builds the next request of a redirect inside `send`, even without following it, and a
    Location such as `javascript:alert(1)` or `http://[::1` makes that raise there. The guarded
    client parses and checks every redirect target itself (`_redirect_target`).
    """
    if response.has_redirect_location:
        response.extensions[_LOCATION] = response.headers["location"]
        del response.headers["location"]


def _redirect_target(current: httpx2.URL, location: str) -> httpx2.URL:
    reject_userinfo(location)
    try:
        return validate_url(current.join(location))
    except InvalidUrlError:
        raise
    except (httpx2.InvalidURL, UnicodeError, ValueError) as error:
        raise InvalidUrlError(MSG_INVALID_REDIRECT) from error


class GuardedClient:
    """GET requests to supplier sites, guarded and with checked redirects.

    `resolver` and `inner_transport` exist for tests (stubbed resolution, `httpx2.MockTransport`);
    production code uses the defaults.
    """

    def __init__(
        self,
        settings: FetchSettings | None = None,
        *,
        resolver: Resolver = system_resolver,
        inner_transport: httpx2.BaseTransport | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.settings = settings or load_fetch_settings()
        # Name-mangled: the raw client is still guarded (its transport is `GuardedTransport`) but
        # has no total deadline, so it is not an attribute other modules can reach by accident.
        self.__client = httpx2.Client(
            transport=GuardedTransport(resolver=resolver, inner=inner_transport),
            trust_env=False,
            follow_redirects=False,
            headers=dict(headers or {}),
            event_hooks={"response": [_take_redirect_location]},
        )

    def __enter__(self) -> "GuardedClient":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.__client.close()

    @contextmanager
    def stream(
        self,
        url: str | httpx2.URL,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[httpx2.Response]:
        """GET `url`, following checked redirects; yield the final response, body not yet read.

        `timeout` (default `FetchSettings.timeout_seconds`) is a total wall-clock limit for the
        whole fetch, body reads inside the block included. `response.url` is the final URL after
        redirects. Raises `FetchError` subclasses for the
        guard's own refusals and `httpx2.HTTPError` subclasses for network failures.
        """
        current = validate_url(url) if isinstance(url, httpx2.URL) else normalise_url(url)
        budget = self.settings.timeout_seconds if timeout is None else timeout
        timed_out = f"The website did not respond within {budget:g} seconds."
        # One wall-clock deadline for the whole fetch: every hop, the connection, the TLS
        # handshake and every read of headers and body (the caller reads the body in this block).
        with fetch_deadline(budget) as deadline:
            for _hop in range(self.settings.max_redirects + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchTimeoutError(timed_out)
                request = self.__client.build_request(
                    "GET", current, headers=dict(headers or {}), timeout=remaining
                )
                try:
                    response = self.__client.send(request, stream=True)
                except (httpx2.InvalidURL, UnicodeError) as error:  # defence in depth
                    raise InvalidUrlError(MSG_INVALID_REDIRECT) from error
                location = response.extensions.get(_LOCATION)
                if location is None:
                    try:
                        yield response
                    finally:
                        response.close()
                    return
                response.close()
                current = _redirect_target(current, location)
        raise TooManyRedirectsError(
            f"The website redirected more than {self.settings.max_redirects} times."
        )

    def get(
        self,
        url: str | httpx2.URL,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx2.Response:
        """Like `stream`, with the body read. For bounded reads (PDFs), use `stream`."""
        with self.stream(url, timeout=timeout, headers=headers) as response:
            response.read()
            return response
