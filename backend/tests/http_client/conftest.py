"""No test in this package can reach a network.

Every socket creation is recorded and refused, and a DNS lookup of a name (rather than a numeric
address) fails the test. Tests use a stubbed resolver and `httpx2.MockTransport`, or the real
transport with this spy to prove where a connection would have gone.
"""

import ipaddress
import socket
from collections.abc import Iterator

import pytest

from tests.http_client.support import NetworkSpy

_real_getaddrinfo = socket.getaddrinfo


@pytest.fixture(autouse=True)
def network(monkeypatch: pytest.MonkeyPatch) -> Iterator[NetworkSpy]:
    spy = NetworkSpy()

    class RefusedSocket(socket.socket):
        def __init__(self, family: int = -1, *args: object, **kwargs: object) -> None:
            spy.sockets.append(family)
            raise OSError("network disabled in tests")

    def numeric_only_getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
        spy.lookups.append(str(host))
        try:
            ipaddress.ip_address(str(host))
        except ValueError as error:
            raise AssertionError(f"real DNS lookup attempted for {host!r}") from error
        return _real_getaddrinfo(host, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(socket, "socket", RefusedSocket)
    monkeypatch.setattr(socket, "getaddrinfo", numeric_only_getaddrinfo)
    yield spy
