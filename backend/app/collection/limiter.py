"""Per-domain rate limit: one request at a time per domain, a minimum delay between them."""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class DomainRateLimiter:
    def __init__(
        self,
        min_delay_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._delay = min_delay_seconds
        self._clock = clock
        self._sleep = sleep
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._last: dict[str, float] = {}

    @contextmanager
    def slot(self, domain: str) -> Iterator[None]:
        """Hold the domain's slot for one request; waits for the minimum delay since the last."""
        with self._guard:
            lock = self._locks.setdefault(domain, threading.Lock())
        with lock:
            last = self._last.get(domain)
            if last is not None:
                wait = self._delay - (self._clock() - last)
                if wait > 0:
                    self._sleep(wait)
            try:
                yield
            finally:
                self._last[domain] = self._clock()
