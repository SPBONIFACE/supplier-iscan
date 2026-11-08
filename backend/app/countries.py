"""Country codes and names (#136).

A supplier identity stores its country as an ISO 3166-1 alpha-2 code, upper-case. People read the
full name in the interface language. The names are a static data file (`content/countries.json`,
English and French, generated once from the ICU region names; no dependency). The frontend uses the
browser's `Intl.DisplayNames` for the screens; this table serves the PDF, the retrieval prompt and
the migration of rows that hold a name.
"""

import json
import unicodedata
from functools import lru_cache
from typing import Final, Literal

from app.content import CONTENT_DIR

Lang = Literal["en", "fr"]
FILE: Final = CONTENT_DIR / "countries.json"

# Names people write that the table does not carry as such.
_ALIASES: Final = {
    "usa": "US",
    "united states of america": "US",
    "uk": "GB",
    "great britain": "GB",
    "royaume uni": "GB",
    "holland": "NL",
    "czech republic": "CZ",
    "south korea": "KR",
    "russian federation": "RU",
}


@lru_cache(maxsize=1)
def _table() -> dict[str, dict[str, str]]:
    table: dict[str, dict[str, str]] = json.loads(FILE.read_text(encoding="utf-8"))
    return table


def _key(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.replace("’", "'")).casefold()
    return "".join(ch for ch in folded if not unicodedata.combining(ch)).strip()


def normalise_code(value: str | None) -> str | None:
    """The upper-case code, or None when `value` is not a two-letter code."""
    text = (value or "").strip()
    return text.upper() if len(text) == 2 and text.isascii() and text.isalpha() else None


def country_name(code: str | None, lang: Lang = "en") -> str | None:
    """The full name for a code in `lang`; an unknown code is returned as it is."""
    if not code:
        return None
    entry = _table().get(code.strip().upper())
    return entry[lang] if entry else code


@lru_cache(maxsize=1)
def _by_name() -> dict[str, str | None]:
    """Normalised name to code; a name used by two codes maps to None (ambiguous)."""
    found: dict[str, str | None] = {}
    for code, names in _table().items():
        for name in names.values():
            key = _key(name)
            found[key] = code if found.get(key, code) == code else None
    for alias, code in _ALIASES.items():
        found[_key(alias)] = code
    return found


def code_for_name(name: str | None) -> str | None:
    """The code of an English or French country name when it maps unambiguously, else None."""
    if not name or not name.strip():
        return None
    return _by_name().get(_key(name))
