"""Polite HTTP access to a registry API (spec, Integrations).

The network itself is behind ``Fetch``, a small injectable interface (request in, response out):
this module imports no networking library. The application's outbound HTTP client provides it
(``app.registries.guarded_fetch``, on the guarded client of #15); tests provide recorded
fixtures.

- a descriptive User-Agent with a contact, sent with every request;
- an optional cap on parallel requests (Wikidata: at most 5);
- an optional sliding-window rate limit (GLEIF: below 60 requests per minute);
- on ``429``, the client waits for ``Retry-After`` before retrying, and every other request to the
  same registry waits too.

Any failure (network error, timeout, error status, error body, invalid JSON) becomes
``RegistryUnavailable``, so that the search service can skip the registry and name it.

An instance belongs to one event loop: the service is built once per process (or per worker loop).
"""

import asyncio
import email.utils
import json
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.registries.models import RegistryName

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]

TOO_MANY_REQUESTS = 429


@dataclass(frozen=True)
class FetchedResponse:
    status_code: int
    body: bytes
    # Header names in lower case.
    headers: Mapping[str, str] = field(default_factory=dict)


class FetchError(Exception):
    """The request did not produce a response."""

    def __init__(self, kind: Literal["timeout", "unreachable"]) -> None:
        super().__init__(kind)
        self.kind: Literal["timeout", "unreachable"] = kind


class Fetch(Protocol):
    """One GET request. Raises ``FetchError`` when no response is received."""

    async def __call__(
        self, url: str, params: Mapping[str, str], headers: Mapping[str, str]
    ) -> FetchedResponse: ...


# Waits longer than this are not worth it in an interactive search: the registry is skipped.
DEFAULT_MAX_RETRY_WAIT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 2
# Used when a 429 carries no usable Retry-After.
DEFAULT_RETRY_DELAY_SECONDS = 1.0


class RegistryUnavailable(Exception):
    def __init__(self, registry: RegistryName, reason: str) -> None:
        super().__init__(f"{registry}: {reason}")
        self.registry = registry
        self.reason = reason


class SlidingWindowRateLimiter:
    """At most ``max_requests`` start within any ``period`` seconds."""

    def __init__(
        self,
        max_requests: int,
        period_seconds: float,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if max_requests <= 0 or period_seconds <= 0:
            raise ValueError("max_requests and period_seconds must be positive")
        self.max_requests = max_requests
        self.period_seconds = period_seconds
        self._clock = clock
        self._sleep = sleep
        self._starts: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                while self._starts and self._starts[0] <= now - self.period_seconds:
                    self._starts.popleft()
                if len(self._starts) < self.max_requests:
                    self._starts.append(now)
                    return
                await self._sleep(self._starts[0] + self.period_seconds - now)


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Seconds to wait from a ``Retry-After`` header (delay in seconds or HTTP date)."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        moment = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    current = time.time() if now is None else now
    return max(0.0, moment.timestamp() - current)


class PoliteHttpClient:
    def __init__(
        self,
        registry: RegistryName,
        fetch: Fetch,
        headers: Mapping[str, str],
        *,
        max_parallel: int | None = None,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_retry_wait_seconds: float = DEFAULT_MAX_RETRY_WAIT_SECONDS,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.registry: RegistryName = registry
        self._fetch = fetch
        self._headers = dict(headers)
        self._semaphore = asyncio.Semaphore(max_parallel) if max_parallel else None
        self._rate_limiter = rate_limiter
        self._max_retries = max_retries
        self._max_retry_wait = max_retry_wait_seconds
        self._clock = clock
        self._sleep = sleep
        self._not_before = 0.0

    def back_off(self, seconds: float) -> None:
        """Hold every request to this registry for ``seconds`` (e.g. on a "too busy" answer)."""
        self._not_before = max(self._not_before, self._clock() + seconds)

    async def _wait_for_backoff(self) -> None:
        while (delay := self._not_before - self._clock()) > 0:
            await self._sleep(delay)

    async def _send(self, url: str, params: Mapping[str, str]) -> FetchedResponse:
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire()
        try:
            return await self._fetch(url, params, self._headers)
        except FetchError as error:
            raise RegistryUnavailable(self.registry, error.kind) from error

    async def get_json(self, url: str, params: Mapping[str, str]) -> Any:
        for attempt in range(self._max_retries + 1):
            await self._wait_for_backoff()
            if self._semaphore is not None:
                async with self._semaphore:
                    response = await self._send(url, params)
            else:
                response = await self._send(url, params)

            if response.status_code == TOO_MANY_REQUESTS:
                delay = parse_retry_after(response.headers.get("retry-after"))
                if delay is None:
                    delay = DEFAULT_RETRY_DELAY_SECONDS * 2**attempt
                if attempt == self._max_retries or delay > self._max_retry_wait:
                    raise RegistryUnavailable(self.registry, "rate limited")
                self.back_off(delay)
                continue
            if response.status_code >= 400:
                raise RegistryUnavailable(self.registry, f"HTTP {response.status_code}")
            try:
                return json.loads(response.body)
            except ValueError as error:
                raise RegistryUnavailable(self.registry, "invalid JSON") from error
        raise RegistryUnavailable(self.registry, "rate limited")  # pragma: no cover
