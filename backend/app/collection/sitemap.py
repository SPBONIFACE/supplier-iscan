"""Sitemaps are hostile input: size-capped after decompression, parsed with `xml.etree`.

Python 3.13 with expat >= 2.4.1 resists entity expansion and never fetches external entities;
the byte cap bounds the rest. A malformed or oversized sitemap is an empty result, never a crash.
"""

import gzip
import logging
import zlib
from dataclasses import dataclass, field
from xml.etree import ElementTree

logger = logging.getLogger(__name__)


@dataclass
class Sitemap:
    urls: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)  # sitemap index entries


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def unpack(content: bytes, max_bytes: int) -> bytes | None:
    """The XML bytes, gunzipped when needed; None when the result would exceed `max_bytes`."""
    if content[:2] == b"\x1f\x8b":
        inflater = zlib.decompressobj(wbits=31)
        try:
            content = inflater.decompress(content, max_bytes + 1)
        except (zlib.error, EOFError, gzip.BadGzipFile):
            return None
    return content if len(content) <= max_bytes else None


def parse_sitemap(content: bytes, max_bytes: int, max_urls: int) -> Sitemap:
    result = Sitemap()
    xml = unpack(content, max_bytes)
    if xml is None:
        logger.warning("Sitemap skipped: oversized or not decompressible")
        return result
    try:
        root = ElementTree.fromstring(xml)  # noqa: S314 - size-capped, expat resists expansion
    except ElementTree.ParseError:
        logger.warning("Sitemap skipped: malformed XML")
        return result
    target = result.children if _local(root.tag) == "sitemapindex" else result.urls
    for element in root.iter():
        if _local(element.tag) == "loc" and element.text and element.text.strip():
            if len(target) >= max_urls:
                logger.warning("Sitemap truncated at %d URLs", max_urls)
                break
            target.append(element.text.strip())
    return result
