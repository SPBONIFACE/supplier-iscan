"""Recorded registry fixtures and fakes for the registry tests. No live registry call is made.

The fixtures were recorded once (27 Oct 2026) from the live Wikidata and GLEIF APIs by running the
service with a recording transport, then trimmed to the fields the service reads. Each exchange
is matched on host, path and the exact query parameters; an unmatched request fails the test.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.registries.http import FetchedResponse, FetchError
from app.registries.service import RegistrySearchService, build_registry_service
from app.registries.settings import RegistrySettings

FIXTURES = Path(__file__).parent / "fixtures"
WIKIDATA_HOST = "www.wikidata.org"
GLEIF_HOST = "api.gleif.org"

# Answers of the live APIs seen while recording, used to simulate failures.
WIKIDATA_TOO_BUSY = {
    "error": {
        "code": "cirrussearch-too-busy-error",
        "info": "Search is currently too busy. Please try again later.",
    }
}
EMPTY_WIKIDATA_SEARCH: dict[str, Any] = {"searchinfo": {"search": ""}, "search": []}
EMPTY_GLEIF_SEARCH: dict[str, Any] = {"meta": {}, "data": []}


@dataclass
class SentRequest:
    host: str
    path: str
    params: dict[str, str]
    headers: dict[str, str]


Override = Callable[[SentRequest], Awaitable[FetchedResponse] | FetchedResponse | None]


def json_response(
    status: int, body: object, headers: Mapping[str, str] | None = None
) -> FetchedResponse:
    return FetchedResponse(
        status_code=status,
        body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=dict(headers or {}),
    )


def load_exchanges(*scenarios: str) -> list[dict[str, Any]]:
    exchanges: list[dict[str, Any]] = []
    for scenario in scenarios:
        data = json.loads((FIXTURES / f"{scenario}.json").read_text(encoding="utf-8"))
        exchanges.extend(data["exchanges"])
    return exchanges


@dataclass
class RecordedRegistries:
    """A ``Fetch`` that answers from recorded exchanges, with optional per-host overrides.

    An override returns a response, raises ``FetchError``, or returns None to fall through to the
    recording.
    """

    exchanges: list[dict[str, Any]] = field(default_factory=list)
    overrides: dict[str, Override] = field(default_factory=dict)
    delay_seconds: float = 0.0
    sent: list[SentRequest] = field(default_factory=list)
    unmatched: list[SentRequest] = field(default_factory=list)
    in_flight: dict[str, int] = field(default_factory=dict)
    max_in_flight: dict[str, int] = field(default_factory=dict)

    async def __call__(
        self, url: str, params: Mapping[str, str], headers: Mapping[str, str]
    ) -> FetchedResponse:
        parts = urlsplit(url)
        host = parts.hostname or ""
        request = SentRequest(host, parts.path, dict(params), dict(headers))
        self.sent.append(request)
        self.in_flight[host] = self.in_flight.get(host, 0) + 1
        self.max_in_flight[host] = max(self.max_in_flight.get(host, 0), self.in_flight[host])
        try:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            override = self.overrides.get(host)
            if override is not None:
                answer = override(request)
                if not isinstance(answer, FetchedResponse) and answer is not None:
                    answer = await answer
                if answer is not None:
                    return answer
            for exchange in self.exchanges:
                if (
                    exchange["host"] == host
                    and exchange["path"] == request.path
                    and exchange["params"] == request.params
                ):
                    return json_response(exchange["status"], exchange["body"])
            self.unmatched.append(request)
            raise AssertionError(f"no recorded exchange for {host}{request.path} {request.params}")
        finally:
            self.in_flight[host] -= 1

    def sent_to(self, host: str) -> list[SentRequest]:
        return [request for request in self.sent if request.host == host]


def failing(kind: str) -> Override:
    def override(request: SentRequest) -> FetchedResponse:
        raise FetchError("timeout" if kind == "timeout" else "unreachable")

    return override


def answering(status: int, body: object, headers: Mapping[str, str] | None = None) -> Override:
    def override(request: SentRequest) -> FetchedResponse:
        return json_response(status, body, headers)

    return override


@dataclass
class FakeTime:
    """Monotonic clock and sleep that advance instantly; every sleep is recorded."""

    now: float = 1_000.0
    sleeps: list[float] = field(default_factory=list)

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += max(0.0, seconds)
        await asyncio.sleep(0)


def make_service(
    fetch: RecordedRegistries,
    time: FakeTime | None = None,
    settings: RegistrySettings | None = None,
) -> RegistrySearchService:
    fake_time = time or FakeTime()
    return build_registry_service(
        settings or RegistrySettings(),
        fetch,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
    )
