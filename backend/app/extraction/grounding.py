"""The grounding check of extraction (spec F3): code, not the model, decides what is kept.

A value is kept only when
- its quote is at most 300 characters,
- the quote is found in the stored redacted text of the cited source, after Unicode (NFKC),
  whitespace and typography normalisation (quotes, apostrophes, dashes), and
- the quote is long enough to carry evidence (`quote_long_enough`).

A kept value must also pass `value_supported`, a narrow guard on numbers; a value it rejects is
counted with the invalid items, not with the grounding failures.

Case, accents and wording are never normalised for the quote: it is verbatim. The text and the
quote are only compared; neither is logged.
"""

import re
import unicodedata
from typing import Final

MAX_QUOTE_CHARS: Final = 300
REDACTION_MARK: Final = "[...]"  # the redaction mark after NFKC (its ellipsis becomes three dots)

# Code points, so that no look-alike character is hidden in this file.
_APOSTROPHES: Final = (0x2018, 0x2019, 0x201A, 0x201B, 0x2032, 0x0060, 0x00B4)
_QUOTES: Final = (0x201C, 0x201D, 0x201E, 0x201F, 0x2033, 0x00AB, 0x00BB)
_DASHES: Final = (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212, 0x2043)
_TYPOGRAPHY: Final = {
    **dict.fromkeys(_APOSTROPHES, "'"),
    **dict.fromkeys(_QUOTES, '"'),
    **dict.fromkeys(_DASHES, "-"),
}
# Soft hyphen, zero-width space, non-joiner, joiner, word joiner, byte order mark: invisible in a
# page, noise in its text.
_INVISIBLE: Final = re.compile(
    "[" + "".join(map(chr, (0xAD, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF))) + "]"
)
_DIGITS: Final = re.compile(r"\d+")
_GROUPED: Final = re.compile(r"\d+(?:[ .,']\d+)*")
_SEPARATORS: Final = {ord("."): None, ord(","): None, ord("'"): None}
_ISO_DATE: Final = re.compile(r"\d{4}-\d{2}(?:-\d{2})?")
_CJK: Final = re.compile("[\u2e80-\u9fff\u3040-\u30ff\uac00-\ud7af\uf900-\ufaff\uff66-\uff9f]")


def normalise(text: str) -> str:
    """NFKC, typography folded to ASCII quotes and hyphens, invisible characters removed and runs
    of whitespace (no-break spaces, line breaks) reduced to one space."""
    text = unicodedata.normalize("NFKC", text).translate(_TYPOGRAPHY)
    return " ".join(_INVISIBLE.sub("", text).split())


def quote_in_text(quote: str, normalised_text: str) -> bool:
    """Whether the quote is in the text (given already normalised, once per source)."""
    needle = normalise(quote)
    return bool(needle) and needle in normalised_text


def is_redacted_quote(quote: str) -> bool:
    """A quote containing the redaction mark is a "Redacted extract"."""
    return REDACTION_MARK in normalise(quote)


def has_cjk(text: str) -> bool:
    """Whether the text has a Han, Hiragana, Katakana or Hangul character."""
    return bool(_CJK.search(text))


def quote_long_enough(quote: str, minimum: int, minimum_cjk: int) -> bool:
    """A quote must carry evidence: at least `minimum` characters after normalisation, or
    `minimum_cjk` when it has a CJK character (a few characters carry more there)."""
    text = normalise(quote)
    return len(text) >= (minimum_cjk if has_cjk(text) else minimum)


def _numbers(text: str) -> set[str]:
    """The numbers of a text as digit strings, thousands separators (space, point, comma,
    apostrophe) and the decimal mark removed, so that "1 200 000", "1.200.000" and "1200000" are
    one number, and "1,2" and "1.2" too. The plain digit runs are kept as well."""
    text = normalise(text)
    return {m.replace(" ", "").translate(_SEPARATORS) for m in _GROUPED.findall(text)} | set(
        _DIGITS.findall(text)
    )


def _found(token: str, in_quote: set[str]) -> bool:
    """A number of the value (as written) is a number of the quote, as one number or as each of
    its digit runs ("2005 2006" against "2005 and 2006")."""
    one = token.replace(" ", "").translate(_SEPARATORS)
    return one in in_quote or all(run in in_quote for run in _DIGITS.findall(token))


def value_supported(value: str, quote: str) -> bool:
    """A guard, not a truth test: it only stops a figure invented next to a real quote. Every
    number of the value must be a number of the quote (see `_numbers`); an ISO date is accepted
    when its year is in the quote. Words are not checked: they may be translated or inferred, and
    the buyer reviews each fact against its quote. A wrong figure that also occurs in the quote
    passes; #22 measures accuracy on the reference set."""
    value = normalise(value)
    if not value:
        return False
    in_quote = _numbers(quote)
    if _ISO_DATE.fullmatch(value):
        return value[:4] in in_quote
    return all(_found(token, in_quote) for token in _GROUPED.findall(value))
