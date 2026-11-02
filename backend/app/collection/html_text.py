"""Text and links of an HTML page, with the standard library only (`html.parser`).

Boilerplate (`script`, `style`, `noscript`, `template`, `nav`, `header`, `footer`, `aside`, and
`role=navigation`) is dropped. The page is decoded with the declared encoding (HTTP header, byte
order mark, then `<meta charset>`) and returned in Unicode NFC.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser

DROPPED = frozenset(
    {"head", "script", "style", "noscript", "template", "nav", "header", "footer", "aside"}
)
VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
BLOCKS = frozenset(
    {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "td"}
)
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_\-:.]+)""", re.I)
_HEADER_CHARSET = re.compile(r"charset\s*=\s*[\"']?([A-Za-z0-9_\-:.]+)", re.I)
_SPACES = re.compile(r"[ \t\r\f\v ]+")


@dataclass
class HtmlPage:
    text: str
    links: list[tuple[str, str]] = field(default_factory=list)  # (href, anchor text)


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._skip: list[str] = []  # open dropped elements
        self._anchor: tuple[str, list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag in VOID:
            return
        if self._skip or tag in DROPPED or values.get("role", "").lower() == "navigation":
            self._skip.append(tag)
            return
        if tag == "a" and values.get("href"):
            self._anchor = (values["href"], [])
        if tag in BLOCKS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br" and not self._skip:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._skip:
            if tag == self._skip[-1]:
                self._skip.pop()
            elif tag in self._skip:  # unbalanced markup: close up to the matching element
                while self._skip.pop() != tag:
                    pass
            return
        if tag == "a" and self._anchor is not None:
            self.links.append((self._anchor[0], " ".join("".join(self._anchor[1]).split())))
            self._anchor = None
        if tag in BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.parts.append(data)
        if self._anchor is not None:
            self._anchor[1].append(data)


def decode(content: bytes, content_type: str = "") -> str:
    """Decode with the declared encoding; else UTF-8, else Windows-1252."""
    declared: str | None = None
    if content.startswith(b"\xef\xbb\xbf"):
        declared = "utf-8-sig"
    elif content.startswith((b"\xff\xfe", b"\xfe\xff")):
        declared = "utf-16"
    else:
        header = _HEADER_CHARSET.search(content_type)
        meta = _META_CHARSET.search(content[:4096])
        if header:
            declared = header.group(1)
        elif meta:
            declared = meta.group(1).decode("ascii", errors="ignore")
    for encoding in (declared, "utf-8", "cp1252"):
        if not encoding:
            continue
        try:
            return content.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")


def normalise_text(text: str) -> str:
    lines = (_SPACES.sub(" ", line).strip() for line in text.splitlines())
    kept = [line for line in lines if line]
    return unicodedata.normalize("NFC", "\n".join(kept))


def parse_html(content: bytes, content_type: str = "") -> HtmlPage:
    extractor = _Extractor()
    extractor.feed(decode(content, content_type))
    extractor.close()
    return HtmlPage(normalise_text("".join(extractor.parts)), extractor.links)
