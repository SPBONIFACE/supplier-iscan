"""The anonymous demo card PDF must not be able to exhaust memory (#50, QA).

A render takes seconds and a lot of memory, and anyone may ask for it. So:
- a rendered file is kept in memory per demo profile and language and reused. The key holds the
  profile's id, which is drawn anew whenever `python -m app.demo load` replaces the set, so a
  stale file is never served; the cache is also bounded (least recently used goes first) and is
  cleared by the command when it runs in the same process;
- at most `MAX_RENDERS` files are rendered at once in this process; a request that cannot get a
  place within `WAIT_SECONDS` is told to retry, with a plain 503 and `Retry-After`.
"""

import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable

MAX_CACHED = 64
MAX_RENDERS = 2
WAIT_SECONDS = 5.0
RETRY_AFTER_SECONDS = 10

BUSY = "Many PDFs are being prepared right now. Please try again in a few seconds."

_lock = threading.Lock()
_cache: OrderedDict[tuple[uuid.UUID, str], bytes] = OrderedDict()
_slots = threading.BoundedSemaphore(MAX_RENDERS)


class Busy(Exception):
    """No render place became free in time."""


def clear() -> None:
    with _lock:
        _cache.clear()


def _get(key: tuple[uuid.UUID, str]) -> bytes | None:
    with _lock:
        found = _cache.get(key)
        if found is not None:
            _cache.move_to_end(key)
        return found


def _put(key: tuple[uuid.UUID, str], content: bytes) -> None:
    with _lock:
        _cache[key] = content
        _cache.move_to_end(key)
        while len(_cache) > MAX_CACHED:
            _cache.popitem(last=False)


def cached_pdf(
    profile_id: uuid.UUID, lang: str, render: Callable[[], bytes], wait: float | None = None
) -> bytes:
    """The file for this profile and language: from the cache, else rendered (at most
    `MAX_RENDERS` at once). Raises Busy when no place is free within the wait."""
    key = (profile_id, lang)
    found = _get(key)
    if found is not None:
        return found
    if not _slots.acquire(timeout=WAIT_SECONDS if wait is None else wait):
        raise Busy
    try:
        found = _get(key)  # another request may have just made it
        if found is None:
            found = render()
            _put(key, found)
        return found
    finally:
        _slots.release()
