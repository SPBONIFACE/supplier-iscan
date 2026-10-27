"""A transport that connects only to an address the URL guard has vetted.

For each request: validate the URL, resolve the host once, refuse unless every address is public,
then send the request to the vetted IP address itself. The host name travels only in the `Host`
header and as the TLS server name (`sni_hostname`), so the certificate is still verified against
the host name, and the inner transport never resolves the name a second time: a DNS answer that
changes between the check and the connection (DNS rebinding) cannot redirect the connection.
"""

import httpx2

from app.http_client.url_guard import (
    IPAddress,
    Resolver,
    port_of,
    resolve_and_vet,
    system_resolver,
    validate_url,
)


def default_inner_transport() -> httpx2.BaseTransport:
    """Direct connections only (no proxy from the environment), certificates verified.

    No keep-alive: a pooled connection is keyed by IP address, so it could otherwise be reused for
    another host name served from the same address, with a TLS session negotiated for the first.
    """
    return httpx2.HTTPTransport(trust_env=False, limits=httpx2.Limits(max_keepalive_connections=0))


class GuardedTransport(httpx2.BaseTransport):
    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        inner: httpx2.BaseTransport | None = None,
    ) -> None:
        self._resolver = resolver
        self._inner = inner if inner is not None else default_inner_transport()

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        url = validate_url(request.url)
        host = url.raw_host.decode("ascii")
        timeouts = request.extensions.get("timeout", {})
        addresses = resolve_and_vet(host, port_of(url), self._resolver, timeouts.get("connect"))
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


def _pinned(
    request: httpx2.Request, url: httpx2.URL, host: str, address: IPAddress
) -> httpx2.Request:
    headers = request.headers.copy()
    headers["Host"] = host if url.port is None else f"{host}:{url.port}"
    return httpx2.Request(
        request.method,
        url.copy_with(host=str(address)),
        headers=headers,
        stream=request.stream,
        extensions={**request.extensions, "sni_hostname": host},
    )
