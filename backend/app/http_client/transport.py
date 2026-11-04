"""A transport that connects only to an address the URL guard has vetted.

For each request: validate the URL, resolve the host once, refuse unless every address is public,
then send the request to the vetted IP address itself. The host name travels only in the `Host`
header and as the TLS server name (`sni_hostname`), so the certificate is still verified against
the host name, and the inner transport never resolves the name a second time: a DNS answer that
changes between the check and the connection (DNS rebinding) cannot redirect the connection.

Total deadline: a timeout given to a socket bounds one read, so a server that sends one byte just
before each read times out could hold a fetch open without limit. `fetch_deadline` sets one
wall-clock deadline for everything done inside it (connection, TLS handshake, every read and write,
on every redirect hop); the network backend of the default inner transport shortens each socket
operation to the time left and fails once the deadline has passed.

Internal module: other modules use `app.http_client` (see its `__all__`), never this one.
"""

import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import httpcore2
import httpx2

from app.http_client.errors import FetchTimeoutError
from app.http_client.url_guard import (
    IPAddress,
    Resolver,
    port_of,
    resolve_and_vet,
    system_resolver,
    validate_url,
)

__all__ = ["GuardedTransport", "fetch_deadline"]

_deadline: ContextVar[float | None] = ContextVar("fetch_deadline", default=None)


@contextmanager
def fetch_deadline(seconds: float) -> Iterator[float]:
    """Bound all network I/O of the guarded transport inside the block to `seconds` in total.

    Yields the deadline (`time.monotonic()` clock). A nested deadline never extends an outer one.
    """
    deadline = time.monotonic() + seconds
    outer = _deadline.get()
    if outer is not None:
        deadline = min(deadline, outer)
    token = _deadline.set(deadline)
    try:
        yield deadline
    finally:
        _deadline.reset(token)


def _bounded(timeout: float | None, timeout_error: type[Exception]) -> float | None:
    """The socket timeout for one operation: `timeout`, shortened to the time left."""
    deadline = _deadline.get()
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise timeout_error("The fetch did not finish within its total time limit.")
    return remaining if timeout is None else min(timeout, remaining)


class _DeadlineStream(httpcore2.NetworkStream):
    def __init__(self, inner: httpcore2.NetworkStream) -> None:
        self._inner = inner

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self._inner.read(max_bytes, _bounded(timeout, httpcore2.ReadTimeout))

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._inner.write(buffer, _bounded(timeout, httpcore2.WriteTimeout))

    def close(self) -> None:
        self._inner.close()

    def start_tls(
        self,
        ssl_context: Any,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore2.NetworkStream:
        bounded = _bounded(timeout, httpcore2.ConnectTimeout)
        return _DeadlineStream(self._inner.start_tls(ssl_context, server_hostname, bounded))

    def get_extra_info(self, info: str) -> Any:
        return self._inner.get_extra_info(info)


class _DeadlineBackend(httpcore2.NetworkBackend):
    def __init__(self, inner: httpcore2.NetworkBackend | None = None) -> None:
        self._inner = inner if inner is not None else httpcore2.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore2.NetworkStream:
        bounded = _bounded(timeout, httpcore2.ConnectTimeout)
        stream = self._inner.connect_tcp(host, port, bounded, local_address, socket_options)
        return _DeadlineStream(stream)

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore2.NetworkStream:
        raise httpcore2.ConnectError("Unix sockets are not used for fetches to supplier sites.")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


class _DeadlineHTTPTransport(httpx2.HTTPTransport):
    """Direct connections only (no proxy from the environment), certificates verified, deadline.

    No keep-alive: a pooled connection is keyed by IP address, so it could otherwise be reused for
    another host name served from the same address, with a TLS session negotiated for the first.
    """

    LIMITS = httpx2.Limits(max_connections=100, max_keepalive_connections=0)

    def __init__(self, network_backend: httpcore2.NetworkBackend | None = None) -> None:
        super().__init__(trust_env=False, limits=self.LIMITS)
        self._pool.close()
        # httpx2.HTTPTransport takes no network backend: its pool is rebuilt with the settings
        # httpx2 gives it and the deadline backend (tests/http_client/test_deadline.py checks
        # both, and that httpx2 still keeps and uses its pool in `_pool`).
        self._pool = httpcore2.ConnectionPool(
            ssl_context=httpx2.create_ssl_context(trust_env=False),
            max_connections=self.LIMITS.max_connections,
            max_keepalive_connections=self.LIMITS.max_keepalive_connections,
            keepalive_expiry=self.LIMITS.keepalive_expiry,
            network_backend=_DeadlineBackend(network_backend),
        )


class GuardedTransport(httpx2.BaseTransport):
    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        inner: httpx2.BaseTransport | None = None,
        before_request: Callable[[httpx2.URL], None] | None = None,
    ) -> None:
        self._resolver = resolver
        # Called with the URL of every request that passed validation, before it is resolved or
        # sent (redirect hops and permission resources included). It may raise to refuse it.
        self._before_request = before_request
        self._inner = inner if inner is not None else _DeadlineHTTPTransport()

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        url = validate_url(request.url)
        if self._before_request is not None:
            self._before_request(url)
        host = url.raw_host.decode("ascii")
        timeout = request.extensions.get("timeout", {}).get("connect")
        deadline = _deadline.get()
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FetchTimeoutError("The fetch did not finish within its total time limit.")
            timeout = remaining if timeout is None else min(timeout, remaining)
        addresses = resolve_and_vet(host, port_of(url), self._resolver, timeout)
        last_error: httpx2.ConnectError | None = None
        for address in addresses:  # every one of them was vetted above
            try:
                return self._inner.handle_request(_pinned(request, url, host, address))
            except httpx2.ConnectError as error:
                last_error = error
        assert last_error is not None  # noqa: S101 - resolve_and_vet never returns an empty list
        raise last_error

    def close(self) -> None:
        self._inner.close()


def _host_header(host: str, port: int | None) -> str:
    # An IPv6 literal is written in brackets in the Host header (RFC 9110, section 7.2).
    authority = f"[{host}]" if ":" in host else host
    return authority if port is None else f"{authority}:{port}"


def _pinned(
    request: httpx2.Request, url: httpx2.URL, host: str, address: IPAddress
) -> httpx2.Request:
    headers = request.headers.copy()
    headers["Host"] = _host_header(host, url.port)
    return httpx2.Request(
        request.method,
        url.copy_with(host=str(address)),
        headers=headers,
        stream=request.stream,
        extensions={**request.extensions, "sni_hostname": host},
    )
