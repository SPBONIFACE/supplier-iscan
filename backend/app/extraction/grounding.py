"""The grounding check of extraction (spec F3): code, not the model, decides what is kept.

A value is kept only when
- its quote is at most 300 characters,
- the quote is found in the stored redacted text of the cited source, after Unicode (NFKC),
  whitespace and typography normalisation (quotes, apostrophes, dashes), and
- the quote is long enough to carry evidence (`quote_long_enough`).

A kept value must also pass `value_supported`, a light guard on figures and words; a value it
rejects is counted with the invalid items, not with the grounding failures.

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


_LEGAL_FORMS = frozenset(
    "sa sas sarl sl spa srl gmbh ag kg bv nv ab as oy ltd limited plc inc llc lp corp corporation "
    "co company pty pte kgaa ug ohg eurl snc se cv & and".split()
)
_GROUP_WORDS = frozenset("holding holdings group groupe gruppe international".split())
_MIN_SHORT_NAME = 4
_SECOND_LEVEL = frozenset("co com org net gov ac edu".split())


def fold(text: str) -> str:
    """`normalise`, then lower-cased and without accents: for the comparison of names."""
    decomposed = unicodedata.normalize("NFKD", normalise(text).casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def supplier_names(legal_name: str) -> list[str]:
    """The folded legal name, and the same without its trailing legal forms ("GmbH & Co. KG",
    "S.A.S.", "Pty Ltd") and group words ("Holding", "Group"), as pages seldom print them. The
    shortened form must keep at least four characters."""
    words = fold(legal_name).replace(".", "").replace(",", " ").split()
    names = [" ".join(words)] if words else []
    while len(words) > 1 and words[-1] in _LEGAL_FORMS | _GROUP_WORDS:
        words = words[:-1]
    short = " ".join(words)
    if short not in names and len(short) >= _MIN_SHORT_NAME:
        names.append(short)
    return names


def website_labels(host: str | None) -> list[str]:
    """The registrable label of the website host (acme-supplies.co.uk gives "acme-supplies" and
    "acme supplies"), when it has at least four characters. Matched as a whole word."""
    parts = fold(host or "").split(".")
    if len(parts) < 2:
        return []
    label = parts[-2]
    if len(parts) >= 3 and len(parts[-1]) == 2 and label in _SECOND_LEVEL:
        label = parts[-3]
    if len(label) < _MIN_SHORT_NAME:
        return []
    return list(dict.fromkeys([label, label.replace("-", " ")]))


def names_supplier(
    folded_text: str, names: list[str], host: str | None, labels: list[str] | None = None
) -> bool:
    """Whether the (folded) text holds one of the supplier's names, its website host or its
    website label as a whole word."""
    if any(name in folded_text for name in names) or bool(host and host in folded_text):
        return True
    return any(
        re.search(rf"(?<!\w){re.escape(label)}(?!\w)", folded_text) for label in labels or []
    )


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


_LETTERS: Final = re.compile(r"[^\W\d_]+")
_DATE: Final = re.compile(r"(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{1,4})")
_MONTHS: Final = frozenset(
    "january february march april may june july august september october november december "
    "janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre "
    "januar februar marz juni juli oktober dezember "
    "enero febrero marzo abril mayo junio julio agosto septiembre noviembre diciembre "
    "gennaio febbraio aprile maggio giugno luglio settembre ottobre dicembre".split()
)
_STOP: Final = {
    "en": "the and of to in is are was for with by on at from that this has have our we its an a",
    "fr": "le la les des du de et un une est sont pour avec par sur dans qui que au aux nous notre"
    " directeur general gerant societe fondee entreprise",
    "de": "der die das und ist sind von mit fur auf im dem den ein eine wir unser"
    " geschaftsfuhrer gegrundet unternehmen gesellschaft",
    "es": "el los las del y es son por con para una en que nuestro nosotros"
    " director gerente sociedad fundada empresa",
    "it": "il lo gli dei della delle e sono per con una che nostro noi"
    " amministratore societa fondata azienda",
}
_STOPWORDS: Final = {lang: frozenset(words.split()) for lang, words in _STOP.items()}
_ALL_STOP: Final = frozenset().union(*_STOPWORDS.values())


def _fold(text: str) -> str:
    """Lower case, accents removed."""
    decomposed = unicodedata.normalize("NFKD", normalise(text).casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _words(text: str) -> list[str]:
    return _LETTERS.findall(_fold(text))


def _meaningful(text: str) -> set[str]:
    return {w for w in _words(text) if len(w) >= 3 and w not in _ALL_STOP}


def _share_a_word(value: str, quote: str) -> bool:
    """A meaningful word in common, a plural or ending tolerated by the first five letters."""
    in_quote = _meaningful(quote)
    return any(
        v == q or (len(v) >= 5 and len(q) >= 5 and v[:5] == q[:5])
        for v in _meaningful(value)
        for q in in_quote
    )


def _quote_is_not_english(quote: str) -> bool:
    """Whether the quote is in another language than English (values are in English): a Han,
    Kana or Hangul character, or more stop-words of fr, de, es or it than of en."""
    if has_cjk(quote):
        return True
    words = _words(quote)
    score = {lang: sum(w in stop for w in words) for lang, stop in _STOPWORDS.items()}
    return max(score["fr"], score["de"], score["es"], score["it"]) > score["en"]


def _date_supported(value: str, quote: str) -> bool | None:
    """None when the value is not a numeric date. Year and day in the quote, and the month as
    digits or by a month name (en, fr, de, es, it)."""
    match = _DATE.fullmatch(value)
    if not match:
        return None
    parts = match.groups()
    years = [p for p in parts if len(p) == 4]
    others = [int(p) for p in parts if len(p) != 4]
    if len(years) != 1 or len(others) != 2:
        return None
    seen = {int(n) for n in _DIGITS.findall(normalise(quote))}
    if int(years[0]) not in seen:
        return False
    named = bool(_MONTHS & set(_words(quote)))
    return all(n in seen for n in others) or (named and any(n in seen for n in others))


def value_supported(value: str, quote: str) -> bool:
    """A guard, not a truth test; the buyer reviews each fact against its quote. A value with
    digits: every number of the value must be a number of the quote (see `_numbers`); an ISO date
    is accepted when its year is in the quote, another numeric date by year, day and month. A
    value without digits: kept when it shares a meaningful word with the quote, or when the quote
    is not in English (a translation). There is no boolean field kind, so "Yes" follows this rule.
    A wrong figure that also occurs in the quote passes; #22 measures accuracy."""
    value = normalise(value)
    if not value:
        return False
    in_quote = _numbers(quote)
    if _ISO_DATE.fullmatch(value):
        return value[:4] in in_quote
    dated = _date_supported(value, quote)
    if dated is not None:
        return dated
    if _DIGITS.search(value):
        return all(_found(token, in_quote) for token in _GROUPED.findall(value))
    return _share_a_word(value, quote) or _quote_is_not_english(quote)
