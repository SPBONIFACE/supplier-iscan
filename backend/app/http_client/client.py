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
from app.http_client.transport import GuardedTransport
from app.http_client.url_guard import Resolver, normalise_url, system_resolver, validate_url

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_REDIRECTS = 5
_MAX_TIMEOUT_SECONDS = 300.0
_MAX_REDIRECTS_LIMIT = 20


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
        self._client = httpx2.Client(
            transport=GuardedTransport(resolver=resolver, inner=inner_transport),
            trust_env=False,
            follow_redirects=False,
            headers=dict(headers or {}),
        )

    def __enter__(self) -> "GuardedClient":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @contextmanager
    def stream(
        self,
        url: str | httpx2.URL,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[httpx2.Response]:
        """GET `url`, following checked redirects; yield the final response, body not yet read.

        `response.url` is the final URL after redirects. Raises `FetchError` subclasses for the
        guard's own refusals and `httpx2.HTTPError` subclasses for network failures.
        """
        current = validate_url(url) if isinstance(url, httpx2.URL) else normalise_url(url)
        budget = self.settings.timeout_seconds if timeout is None else timeout
        deadline = time.monotonic() + budget
        for _hop in range(self.settings.max_redirects + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FetchTimeoutError(f"The website did not respond within {budget:g} seconds.")
            request = self._client.build_request(
                "GET", current, headers=dict(headers or {}), timeout=remaining
            )
            response = self._client.send(request, stream=True)
            if not response.is_redirect:
                try:
                    yield response
                finally:
                    response.close()
                return
            location = response.headers["location"]
            response.close()
            try:
                current = validate_url(current.join(location))
            except (httpx2.InvalidURL, UnicodeError, ValueError) as error:
                if isinstance(error, InvalidUrlError):
                    raise
                raise InvalidUrlError("The website redirected to an invalid address.") from error
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
