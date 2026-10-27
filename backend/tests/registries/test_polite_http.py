"""The polite HTTP layer: parallel cap, rate limit, Retry-After, failures (issue #14)."""

import asyncio
import email.utils
from collections.abc import Mapping

import pytest

from app.registries.http import (
    FetchedResponse,
    FetchError,
    PoliteHttpClient,
    RegistryUnavailable,
    SlidingWindowRateLimiter,
    parse_retry_after,
)
from app.registries.wikidata import WikidataRegistry
from tests.registries.support import FakeTime, json_response

URL = "https://registry.example/api"
HEADERS = {"User-Agent": "SupplierIScan/test (contact)"}


class ScriptedFetch:
    """Answers from a list, in order; records the fake time of each request."""

    def __init__(self, answers: list[FetchedResponse | FetchError], time: FakeTime) -> None:
        self.answers = answers
        self.time = time
        self.sent_at: list[float] = []
        self.headers: list[dict[str, str]] = []

    async def __call__(
        self, url: str, params: Mapping[str, str], headers: Mapping[str, str]
    ) -> FetchedResponse:
        self.sent_at.append(self.time.now)
        self.headers.append(dict(headers))
        answer = self.answers.pop(0)
        if isinstance(answer, FetchError):
            raise answer
        return answer


def client(fetch: ScriptedFetch, time: FakeTime, **options: object) -> PoliteHttpClient:
    return PoliteHttpClient(
        "wikidata",
        fetch,
        HEADERS,
        clock=time.clock,
        sleep=time.sleep,
        **options,  # type: ignore[arg-type]
    )


def test_sends_the_configured_headers() -> None:
    time = FakeTime()
    fetch = ScriptedFetch([json_response(200, {"ok": True})], time)

    answer = asyncio.run(client(fetch, time).get_json(URL, {}))

    assert answer == {"ok": True}
    assert fetch.headers == [HEADERS]


def test_429_waits_for_retry_after_seconds_then_retries() -> None:
    time = FakeTime()
    fetch = ScriptedFetch(
        [json_response(429, {}, {"retry-after": "12"}), json_response(200, {"ok": True})], time
    )

    answer = asyncio.run(client(fetch, time).get_json(URL, {}))

    assert answer == {"ok": True}
    assert time.sleeps == [12.0]
    assert fetch.sent_at[1] - fetch.sent_at[0] == 12.0


def test_429_without_retry_after_backs_off_before_retrying() -> None:
    time = FakeTime()
    fetch = ScriptedFetch([json_response(429, {}), json_response(200, {"ok": True})], time)

    asyncio.run(client(fetch, time).get_json(URL, {}))

    assert fetch.sent_at[1] > fetch.sent_at[0]


def test_429_also_holds_other_requests_to_the_same_registry() -> None:
    time = FakeTime()
    fetch = ScriptedFetch(
        [
            json_response(429, {}, {"retry-after": "5"}),
            json_response(200, {"first": True}),
            json_response(200, {"second": True}),
        ],
        time,
    )
    polite = client(fetch, time)

    async def run() -> None:
        await polite.get_json(URL, {})
        await polite.get_json(URL, {})

    asyncio.run(run())

    assert fetch.sent_at[1] >= fetch.sent_at[0] + 5


def test_repeated_429_gives_up_and_names_the_registry() -> None:
    time = FakeTime()
    fetch = ScriptedFetch([json_response(429, {}, {"retry-after": "1"})] * 3, time)

    with pytest.raises(RegistryUnavailable) as raised:
        asyncio.run(client(fetch, time, max_retries=2).get_json(URL, {}))

    assert raised.value.registry == "wikidata"
    assert len(fetch.sent_at) == 3


def test_retry_after_longer_than_the_limit_is_not_waited_for() -> None:
    time = FakeTime()
    fetch = ScriptedFetch([json_response(429, {}, {"retry-after": "120"})], time)

    with pytest.raises(RegistryUnavailable, match="rate limited"):
        asyncio.run(client(fetch, time, max_retry_wait_seconds=30).get_json(URL, {}))

    assert time.sleeps == []


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (FetchError("timeout"), "timeout"),
        (FetchError("unreachable"), "unreachable"),
        (json_response(503, {}), "HTTP 503"),
        (FetchedResponse(status_code=200, body=b"not json"), "invalid JSON"),
    ],
)
def test_failures_become_registry_unavailable(
    answer: FetchedResponse | FetchError, reason: str
) -> None:
    time = FakeTime()
    fetch = ScriptedFetch([answer], time)

    with pytest.raises(RegistryUnavailable) as raised:
        asyncio.run(client(fetch, time).get_json(URL, {}))

    assert raised.value.reason == reason


def test_parse_retry_after_accepts_seconds_and_http_dates() -> None:
    now = 1_800_000_000.0
    date = email.utils.formatdate(now + 30, usegmt=True)

    assert parse_retry_after("7") == 7.0
    assert parse_retry_after(date, now=now) == pytest.approx(30.0)
    assert parse_retry_after(email.utils.formatdate(now - 30, usegmt=True), now=now) == 0.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("soon") is None


def test_at_most_five_requests_run_in_parallel() -> None:
    in_flight = 0
    peak = 0

    async def slow(
        url: str, params: Mapping[str, str], headers: Mapping[str, str]
    ) -> FetchedResponse:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return json_response(200, {})

    async def run() -> None:
        polite = PoliteHttpClient("wikidata", slow, HEADERS, max_parallel=5)
        await asyncio.gather(*(polite.get_json(URL, {"n": str(n)}) for n in range(12)))

    asyncio.run(run())

    assert peak == 5


def test_sliding_window_limits_requests_per_period() -> None:
    time = FakeTime()
    limiter = SlidingWindowRateLimiter(50, 60.0, clock=time.clock, sleep=time.sleep)
    starts: list[float] = []

    async def run() -> None:
        for _ in range(160):
            await limiter.acquire()
            starts.append(time.now)

    asyncio.run(run())

    for index, moment in enumerate(starts):
        assert len([t for t in starts[index:] if t < moment + 60.0]) <= 50
    # Not slower than needed: 160 requests at 50 per minute fit in a little over 3 minutes.
    assert starts[-1] - starts[0] <= 3 * 60.0


def test_rate_limiter_rejects_nonsense_settings() -> None:
    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(0, 60.0)


def test_wikidata_too_busy_answer_is_retried_after_a_pause() -> None:
    time = FakeTime()
    busy = json_response(200, {"error": {"code": "cirrussearch-too-busy-error"}})
    fetch = ScriptedFetch([busy, json_response(200, {"search": []})], time)

    from app.registries.cache import InMemoryRegistryCache

    registry = WikidataRegistry(client(fetch, time), InMemoryRegistryCache(60, clock=time.clock))
    answer = asyncio.run(registry._call({"action": "wbsearchentities"}))

    assert answer == {"search": []}
    assert len(fetch.sent_at) == 2
    assert fetch.sent_at[1] - fetch.sent_at[0] >= 2.0


def test_wikidata_persistent_too_busy_answer_fails_the_registry() -> None:
    time = FakeTime()
    busy = json_response(200, {"error": {"code": "cirrussearch-too-busy-error"}})
    fetch = ScriptedFetch([busy] * 3, time)

    from app.registries.cache import InMemoryRegistryCache

    registry = WikidataRegistry(client(fetch, time), InMemoryRegistryCache(60, clock=time.clock))

    with pytest.raises(RegistryUnavailable, match="too-busy"):
        asyncio.run(registry._call({"action": "wbsearchentities"}))
    assert len(fetch.sent_at) == 3
