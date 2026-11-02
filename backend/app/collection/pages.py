"""Which pages matter: home, about, sustainability/ESG, certifications/quality and locations,
recognised by their URL path or link text in English, French and German (accent-folded).
"""

import re
import unicodedata
from urllib.parse import unquote, urlsplit

# Order is the priority when the page cap leaves room for only some of them.
PAGE_KINDS = ("home", "about", "sustainability", "certifications", "locations")
KEYWORDS: dict[str, tuple[str, ...]] = {
    "about": (
        "about",
        "company",
        "who we are",
        "our story",
        "a propos",
        "qui sommes nous",
        "entreprise",
        "societe",
        "notre histoire",
        "ueber uns",
        "uber uns",
        "unternehmen",
        "wir ueber uns",
        "über uns",
    ),
    "sustainability": (
        "sustainab",
        "esg",
        "csr",
        "environment",
        "responsib",
        "rse",
        "developpement durable",
        "responsabilite",
        "engagement",
        "nachhaltigkeit",
        "verantwortung",
        "umwelt",
    ),
    "certifications": (
        "certif",
        "quality",
        "iso",
        "accreditation",
        "qualite",
        "norme",
        "zertifi",
        "qualitaet",
        "qualitat",
        "normen",
    ),
    "locations": (
        "location",
        "sites",
        "offices",
        "contact",
        "where",
        "implantation",
        "nos sites",
        "adresse",
        "standort",
        "kontakt",
        "niederlassung",
        "anfahrt",
    ),
}
_NON_WORD = re.compile(r"[^a-z0-9]+")


def fold(text: str) -> str:
    """Lower case, without accents; `ß` and umlauts become ASCII (`ae`, `ss`)."""
    text = unquote(text).lower().replace("ß", "ss")
    for source, target in (("ä", "ae"), ("ö", "oe"), ("ü", "ue")):
        text = text.replace(source, target)
    text = unicodedata.normalize("NFKD", text)
    return " ".join(
        _NON_WORD.sub(" ", "".join(c for c in text if not unicodedata.combining(c))).split()
    )


def _matches(keyword: str, words: str) -> bool:
    keyword = fold(keyword)
    if len(keyword) <= 3:  # short ones ("iso", "esg", "rse") only as whole words
        return f" {keyword} " in f" {words} "
    return keyword in words


def classify(url: str, anchor: str = "") -> str | None:
    """The page kind of a URL (and the text of the link to it), or None."""
    path = urlsplit(url).path
    if path in ("", "/"):
        return "home"
    words = fold(f"{path} {anchor}")
    for kind in PAGE_KINDS[1:]:
        if any(_matches(keyword, words) for keyword in KEYWORDS[kind]):
            return kind
    return None
