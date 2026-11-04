"""The grounding check of extraction (spec F3): code, not the model, decides what is kept.

A value is kept only when
- its quote is at most 300 characters,
- the quote is found in the stored redacted text of the cited source, after Unicode (NFKC),
  whitespace and typography normalisation (quotes, apostrophes, dashes), and
- the value is supported by that quote (`value_supported`).

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
_NUMBER: Final = re.compile(r"\d+")
_LETTERS: Final = re.compile(r"[^\W\d_]+")


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


def fold(text: str) -> str:
    """For comparing a value with its evidence: normalised, and case and accents do not matter."""
    decomposed = unicodedata.normalize("NFKD", normalise(text).casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def value_supported(value: str, quote: str, folded_text: str) -> bool:
    """A cheap check that the value comes from the evidence and is not invented next to a real
    quote: every number of the value is a number of the quote, and every word of the value (three
    characters or more; a run of CJK characters counts as one word) is in the source text
    (`folded_text`, folded once per source with `fold`).

    It does not prove that the value means what the quote says (a wrong figure that also occurs
    in the quote passes); #22 measures accuracy on the reference set.
    """
    folded_value = fold(value)
    numbers, words = _NUMBER.findall(folded_value), _LETTERS.findall(folded_value)
    if not numbers and not words:
        return False
    quote_numbers = set(_NUMBER.findall(fold(quote)))
    if any(number not in quote_numbers for number in numbers):
        return False
    return all(word in folded_text for word in words if len(word) >= 3 or not word.isascii())
