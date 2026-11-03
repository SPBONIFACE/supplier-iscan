"""Synthetic fixture sites for the collection tests: no personal data, no real network."""

import gzip
import io
from collections.abc import Callable, Iterator

import httpx2
from pypdf import PdfWriter

from app.collection.collector import Collector
from app.collection.settings import CollectionSettings
from app.collection.source_store import SourceRecord
from app.crawl import EmptySuppressionList, PermittedFetcher, build_client
from app.crawl.permissions import DomainPermission
from tests.http_client.support import PUBLIC_V4, MockSite, StubResolver

HOST = "acme.example"
OTHER = "registry.example"
INTERNAL = "internal.example"
RESOLVER = StubResolver({HOST: [PUBLIC_V4], OTHER: [PUBLIC_V4], INTERNAL: ["10.0.0.5"]})
CONTACT = "https://iscan.example/contact"


def html(body: str, charset: str = "utf-8", meta: str = "") -> httpx2.Response:
    document = f"<html><head>{meta}<title>t</title></head><body>{body}</body></html>"
    return httpx2.Response(
        200, content=document.encode(charset), headers={"content-type": "text/html"}
    )


def xml(body: str, gz: bool = False) -> httpx2.Response:
    data = body.encode()
    return httpx2.Response(200, content=gzip.compress(data) if gz else data)


def urlset(*paths: str) -> str:
    entries = "".join(f"<url><loc>https://{HOST}{p}</loc></url>" for p in paths)
    return f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'


def pdf_bytes(
    text: str = "Annual report of Acme Supplies", author: str | None = "A. Writer"
) -> bytes:
    """A one-page PDF whose text layer is `text` (hand-built; ASCII text only)."""
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    info = f"<< /Author ({author}) >>".encode() if author else None
    if info:
        objects.append(info)
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    trailer = b"trailer\n<< /Size %d /Root 1 0 R" % (len(objects) + 1)
    if info:
        trailer += b" /Info %d 0 R" % len(objects)
    out += trailer + b" >>\nstartxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)


def pdf_response(content: bytes) -> httpx2.Response:
    return httpx2.Response(200, content=content, headers={"content-type": "application/pdf"})


def encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.encrypt("secret")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def chunks(total: int, size: int, seen: list[int]) -> Iterator[bytes]:
    """A body of `total` bytes with no Content-Length; `seen` counts the bytes actually pulled."""
    sent = 0
    while sent < total:
        piece = min(size, total - sent)
        sent += piece
        seen.append(piece)
        yield b"%" * piece


Setup = tuple[Collector, MockSite, list[SourceRecord], list[float], list[DomainPermission]]


def make_collector(
    pages: dict[tuple[str, str], httpx2.Response],
    settings: CollectionSettings | None = None,
    check: Callable[[], None] = lambda: None,
) -> Setup:
    """A collector over a mock site; `sleeps` records every delay (none really sleeps)."""
    site = MockSite(pages)
    client = build_client(CONTACT, resolver=RESOLVER, inner_transport=site.transport)
    recorded: list[DomainPermission] = []
    fetcher = PermittedFetcher(client, EmptySuppressionList(), recorded.append)
    stored: list[SourceRecord] = []
    sleeps: list[float] = []
    now = [0.0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    from app.collection.limiter import DomainRateLimiter

    limits = settings or CollectionSettings(min_delay_seconds=0.0, backoff_seconds=0.0)
    limiter = DomainRateLimiter(limits.min_delay_seconds, clock=lambda: now[0], sleep=sleep)
    collector = Collector(
        fetcher, limits, stored.append, limiter=limiter, sleep=sleep, check_stop=check
    )
    return collector, site, stored, sleeps, recorded
