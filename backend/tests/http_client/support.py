"""Helpers for the HTTP client tests: stubbed resolution, network spy, mock sites."""

import ipaddress
import socket
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import httpx2

from app.http_client import FetchSettings, GuardedClient
from app.http_client.url_guard import IPAddress

PUBLIC_V4 = "93.184.215.14"
OTHER_PUBLIC_V4 = "93.184.215.15"
PUBLIC_V6 = "2606:2800:21f:cb07:6820:80da:af6b:8b2c"


@dataclass
class NetworkSpy:
    sockets: list[int] = field(default_factory=list)  # address families of attempted sockets
    lookups: list[str] = field(default_factory=list)  # hosts passed to socket.getaddrinfo


class StubResolver:
    """Answers from a table; a host missing from the table does not resolve."""

    def __init__(self, answers: Mapping[str, Sequence[str] | BaseException] | None = None) -> None:
        self.answers = dict(answers or {})
        self.calls: list[tuple[str, int]] = []

    def __call__(self, host: str, port: int) -> list[IPAddress]:
        self.calls.append((host, port))
        answer = self.answers.get(host)
        if answer is None:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        if isinstance(answer, BaseException):
            raise answer
        return [ipaddress.ip_address(address) for address in answer]


class SequenceResolver:
    """Returns the next answer on each call: a DNS answer that changes (rebinding)."""

    def __init__(self, *answers: Sequence[str]) -> None:
        self._answers = list(answers)
        self.calls: list[str] = []

    def __call__(self, host: str, port: int) -> list[IPAddress]:
        self.calls.append(host)
        answer = self._answers[min(len(self.calls), len(self._answers)) - 1]
        return [ipaddress.ip_address(address) for address in answer]


@dataclass
class SeenRequest:
    url: str
    connect_host: str
    host_header: str
    sni_hostname: str | None


class MockSite:
    """A `MockTransport` whose pages are keyed by (Host header, path); records every request."""

    def __init__(self, pages: dict[tuple[str, str], httpx2.Response] | None = None) -> None:
        self.pages = dict(pages or {})
        self.seen: list[SeenRequest] = []
        self.transport = httpx2.MockTransport(self._handle)
        self.error: Callable[[httpx2.Request], None] | None = None

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        host_header = request.headers["host"]
        self.seen.append(
            SeenRequest(
                url=str(request.url),
                connect_host=request.url.host,
                host_header=host_header,
                sni_hostname=request.extensions.get("sni_hostname"),
            )
        )
        if self.error is not None:
            self.error(request)
        page = self.pages.get((host_header, request.url.path))
        return page if page is not None else httpx2.Response(404)


def redirect(location: str, status: int = 302) -> httpx2.Response:
    return httpx2.Response(status, headers={"Location": location})


def make_client(
    resolver: Callable[[str, int], Sequence[IPAddress]],
    site: MockSite | None = None,
    settings: FetchSettings | None = None,
) -> GuardedClient:
    return GuardedClient(
        settings or FetchSettings(),
        resolver=resolver,
        inner_transport=site.transport if site is not None else None,
    )
