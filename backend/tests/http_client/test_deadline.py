"""Criterion 5 (QA FAIL on #15): the timeout bounds the whole fetch, not each socket read.

These tests run the real transport against a server on the loopback interface, started by the test
itself. The address vetting is patched to accept loopback for them only, and the `network` fixture
below lets a socket connect to 127.0.0.1 and nowhere else: no test reaches the internet.
"""

import ipaddress
import socket
import ssl
import threading
import time
from collections.abc import Callable, Iterator

import httpcore2
import httpx2
import pytest

from app.http_client import (
    FetchSettings,
    FetchTimeoutError,
    GuardedClient,
    check_website,
    url_guard,
)
from app.http_client.transport import (
    _DeadlineBackend,
    _DeadlineHTTPTransport,
    fetch_deadline,
)
from tests.http_client.support import NetworkSpy, StubResolver

BUDGET = 1.0
# Slack for thread scheduling on a loaded CI machine; far below the drip duration below.
SLACK = 0.8
DRIP_INTERVAL = 0.2  # well under BUDGET: a per-read timeout never fires
DRIP_DURATION = 6.0  # what the check would take if only each read were bounded

_RealSocket = socket.socket


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> Iterator[NetworkSpy]:
    """Overrides the package fixture: sockets may connect to the loopback interface only."""
    spy = NetworkSpy()

    class LoopbackOnlySocket(_RealSocket):
        def connect(self, address: object) -> None:
            host = address[0] if isinstance(address, tuple) else address
            if not ipaddress.ip_address(str(host)).is_loopback:
                raise AssertionError(f"connection outside loopback attempted: {address!r}")
            spy.sockets.append(self.family)
            super().connect(address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket, "socket", LoopbackOnlySocket)
    yield spy


@pytest.fixture(autouse=True)
def allow_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    original = url_guard.is_public_address
    monkeypatch.setattr(
        url_guard, "is_public_address", lambda address: address.is_loopback or original(address)
    )


Handler = Callable[[_RealSocket, threading.Event], None]


@pytest.fixture
def serve() -> Iterator[Callable[[Handler], int]]:
    """Start a one-connection-at-a-time loopback server running `handler`; return its port."""
    stop = threading.Event()
    threads: list[threading.Thread] = []
    listeners: list[_RealSocket] = []

    def start(handler: Handler) -> int:
        listener = _RealSocket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(0.1)
        listeners.append(listener)

        def run() -> None:
            while not stop.is_set():
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                with connection:
                    connection.settimeout(DRIP_DURATION)
                    connection.recv(65536)  # the request
                    try:
                        handler(connection, stop)
                    except OSError:
                        pass  # the client gave up and closed the connection

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        threads.append(thread)
        return int(listener.getsockname()[1])

    yield start
    stop.set()
    for thread in threads:
        thread.join(timeout=2)
    for listener in listeners:
        listener.close()


def drip(connection: _RealSocket, stop: threading.Event, head: bytes, line: bytes) -> None:
    connection.sendall(head)
    end = time.monotonic() + DRIP_DURATION
    while time.monotonic() < end and not stop.wait(DRIP_INTERVAL):
        connection.sendall(line)


def header_drip(connection: _RealSocket, stop: threading.Event) -> None:
    drip(connection, stop, b"HTTP/1.1 200 OK\r\n", b"X-Drip: a\r\n")


def body_drip(connection: _RealSocket, stop: threading.Event) -> None:
    drip(connection, stop, b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n", b"a")


def client_for(settings: FetchSettings) -> GuardedClient:
    return GuardedClient(settings, resolver=StubResolver({"slow.example": ["127.0.0.1"]}))


def test_a_server_that_drips_headers_is_stopped_at_the_website_check_timeout(
    serve: Callable[[Handler], int], network: NetworkSpy
) -> None:
    port = serve(header_drip)
    settings = FetchSettings(website_check_timeout_seconds=BUDGET)

    started = time.monotonic()
    with client_for(settings) as client:
        result = check_website(f"http://slow.example:{port}/", client)
    elapsed = time.monotonic() - started

    assert result.failure == "timeout"
    assert result.reason == f"The website did not respond within {BUDGET:g} seconds."
    assert elapsed < BUDGET + SLACK
    assert network.sockets  # the server was really reached


def test_a_server_that_drips_the_body_is_stopped_at_the_fetch_timeout(
    serve: Callable[[Handler], int],
) -> None:
    port = serve(body_drip)

    started = time.monotonic()
    with (
        client_for(FetchSettings(timeout_seconds=BUDGET)) as client,
        pytest.raises(httpx2.TimeoutException),
    ):
        client.get(f"http://slow.example:{port}/")

    assert time.monotonic() - started < BUDGET + SLACK


def test_one_deadline_covers_every_redirect_hop(serve: Callable[[Handler], int]) -> None:
    def slow_redirect(connection: _RealSocket, stop: threading.Event) -> None:
        stop.wait(0.4)  # each hop alone stays under the budget
        connection.sendall(b"HTTP/1.1 302 Found\r\nLocation: /again\r\nContent-Length: 0\r\n\r\n")

    port = serve(slow_redirect)
    settings = FetchSettings(timeout_seconds=BUDGET, max_redirects=10)

    started = time.monotonic()
    with (
        client_for(settings) as client,
        pytest.raises((httpx2.TimeoutException, FetchTimeoutError)),
    ):
        client.get(f"http://slow.example:{port}/")

    assert time.monotonic() - started < BUDGET + SLACK


def test_a_prompt_server_is_reachable_through_the_deadline_transport(
    serve: Callable[[Handler], int],
) -> None:
    def prompt(connection: _RealSocket, _stop: threading.Event) -> None:
        connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

    port = serve(prompt)

    with client_for(FetchSettings(timeout_seconds=BUDGET)) as client:
        response = client.get(f"http://slow.example:{port}/")

    assert response.status_code == 200
    assert response.text == "ok"


# The rebuilt pool (QA on #15): `_DeadlineHTTPTransport` replaces the private `_pool` of
# `httpx2.HTTPTransport`. The tests below fail loudly if an httpx2 upgrade moves or reshapes it,
# or if the rebuilt pool drifts from the settings httpx2 itself would use.

_POOL_STATE = {"_connections", "_requests", "_optional_thread_lock"}  # mutable state, not settings


def _stock_transport() -> httpx2.HTTPTransport:
    """The transport `_DeadlineHTTPTransport` starts from, before its pool is rebuilt."""
    return httpx2.HTTPTransport(trust_env=False, limits=_DeadlineHTTPTransport.LIMITS)


def test_httpx2_still_holds_its_pool_where_the_deadline_transport_replaces_it() -> None:
    stock = _stock_transport()

    pool = vars(stock).get("_pool")

    assert type(pool) is httpcore2.ConnectionPool, (
        "httpx2.HTTPTransport no longer keeps an httpcore2.ConnectionPool in `_pool`: "
        "_DeadlineHTTPTransport must be revisited before this httpx2 version is used."
    )
    stock.close()


def test_httpx2_sends_every_request_through_the_replaced_pool() -> None:
    sent: list[httpcore2.Request] = []

    class RecordingPool(httpcore2.ConnectionPool):
        def handle_request(self, request: httpcore2.Request) -> httpcore2.Response:
            sent.append(request)
            return httpcore2.Response(200, content=b"ok")

    transport = _DeadlineHTTPTransport()
    transport._pool.close()  # noqa: SLF001
    transport._pool = RecordingPool()  # noqa: SLF001

    response = transport.handle_request(httpx2.Request("GET", "http://93.184.215.14/"))
    response.read()

    assert len(sent) == 1
    assert response.content == b"ok"


def test_the_default_inner_transport_uses_the_deadline_backend() -> None:
    transport = _DeadlineHTTPTransport()

    assert type(transport._pool) is httpcore2.ConnectionPool  # noqa: SLF001
    assert isinstance(transport._pool._network_backend, _DeadlineBackend)  # noqa: SLF001
    transport.close()


def test_the_rebuilt_pool_has_every_setting_httpx2_would_give_it() -> None:
    stock = _stock_transport()
    rebuilt = _DeadlineHTTPTransport()
    stock_settings = vars(stock._pool)  # noqa: SLF001
    rebuilt_settings = vars(rebuilt._pool)  # noqa: SLF001

    assert set(rebuilt_settings) == set(stock_settings)
    differing = {
        name
        for name in set(stock_settings) - _POOL_STATE
        if rebuilt_settings[name] != stock_settings[name]
    }
    # Only the network backend (the deadline) and the SSL context object (built the same way,
    # checked below) differ from what httpx2 builds.
    assert differing <= {"_network_backend", "_ssl_context"}
    assert rebuilt_settings["_max_keepalive_connections"] == 0
    assert rebuilt_settings["_proxy"] is None
    assert rebuilt_settings["_http1"] is True
    assert rebuilt_settings["_http2"] is False
    assert rebuilt_settings["_retries"] == 0
    stock.close()
    rebuilt.close()


def test_the_rebuilt_pool_verifies_certificates_and_host_names() -> None:
    stock = _stock_transport()
    rebuilt = _DeadlineHTTPTransport()
    context = rebuilt._pool._ssl_context  # noqa: SLF001
    stock_context = stock._pool._ssl_context  # noqa: SLF001

    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert type(context) is type(stock_context)
    assert context.minimum_version == stock_context.minimum_version
    assert context.options == stock_context.options
    stock.close()
    rebuilt.close()


def test_no_connection_stays_open_between_requests(
    serve: Callable[[Handler], int], network: NetworkSpy
) -> None:
    closed_by_client: list[bool] = []

    def keep_alive(connection: _RealSocket, _stop: threading.Event) -> None:
        # A keep-alive response; the server then waits for the client to close the connection.
        connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        closed_by_client.append(connection.recv(1) == b"")

    port = serve(keep_alive)
    transport = _DeadlineHTTPTransport()

    with GuardedClient(
        FetchSettings(timeout_seconds=BUDGET),
        resolver=StubResolver({"slow.example": ["127.0.0.1"]}),
        inner_transport=transport,
    ) as client:
        for _ in range(2):
            assert client.get(f"http://slow.example:{port}/").text == "ok"
            assert transport._pool.connections == []  # noqa: SLF001

    assert len(network.sockets) == 2  # one new connection per request, none reused
    deadline = time.monotonic() + 2
    while len(closed_by_client) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert closed_by_client == [True, True]


def test_a_nested_deadline_never_extends_the_outer_one() -> None:
    with fetch_deadline(1.0) as outer, fetch_deadline(60.0) as inner:
        assert inner == outer
