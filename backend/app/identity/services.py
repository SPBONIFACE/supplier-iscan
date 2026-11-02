"""What the identity agent needs from outside: registries, outbound HTTP, one event loop.

The registry service is asynchronous and its rate limiter and semaphore belong to one event loop,
while the endpoints are synchronous (they run in worker threads). `AsyncRunner` owns that one loop
in a daemon thread; the endpoints hand it coroutines. Built on first use, so the application starts
without opening a thread or a connection pool.
"""

import asyncio
import threading
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, Protocol

from app.http_client import GuardedClient
from app.registries import (
    RegistrySearchQuery,
    RegistrySearchResult,
    build_registry_service,
    load_registry_settings,
)
from app.registries.guarded_fetch import GuardedFetch


class RegistrySearcher(Protocol):
    async def search(self, query: RegistrySearchQuery) -> RegistrySearchResult: ...


class AsyncRunner:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def run[T](self, coroutine: Coroutine[Any, Any, T]) -> T:
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result()

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


@dataclass
class IdentityServices:
    registries: RegistrySearcher
    runner: AsyncRunner
    # The guarded client of #15: the only way the identity chat reaches a supplier's website.
    http: GuardedClient

    def close(self) -> None:
        self.runner.close()
        self.http.close()


def build_identity_services() -> IdentityServices:
    registry_settings = load_registry_settings()
    client = GuardedClient()
    fetch = GuardedFetch(client, registry_settings.timeout_seconds)
    return IdentityServices(
        registries=build_registry_service(registry_settings, fetch),
        runner=AsyncRunner(),
        http=client,
    )
