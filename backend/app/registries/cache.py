"""Cache of registry identifiers and candidate data.

The cache holds registry public data only: candidate records, labels and identifiers as published
by Wikidata and GLEIF. Keys are built from the registry, the kind of entry and the normalised
supplier name or registry identifier; the search hints never reach the cache.

``RegistryCache`` is the interface. ``InMemoryRegistryCache`` is the implementation used for now
(one per process); a database-backed implementation can follow behind the same interface. Values
must be JSON-compatible (dicts, lists, strings, numbers, booleans, None) so that such an
implementation can store them as they are.
"""

import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Protocol

type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None

DEFAULT_MAX_ENTRIES = 10_000


class RegistryCache(Protocol):
    def get(self, key: str) -> JsonValue | None:
        """Return the cached value, or None when absent or expired."""
        ...

    def set(self, key: str, value: JsonValue) -> None: ...


class InMemoryRegistryCache:
    """Time-limited, size-bounded cache. The oldest entries are evicted first."""

    def __init__(
        self,
        ttl_seconds: float,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, JsonValue]] = OrderedDict()

    def get(self, key: str) -> JsonValue | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._entries[key]
            return None
        return value

    def set(self, key: str, value: JsonValue) -> None:
        self._entries.pop(key, None)
        self._entries[key] = (self._clock() + self._ttl, value)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)

    def items(self) -> list[tuple[str, JsonValue]]:
        """Live entries, for inspection in tests and diagnostics."""
        now = self._clock()
        return [(key, value) for key, (expires, value) in self._entries.items() if now < expires]
