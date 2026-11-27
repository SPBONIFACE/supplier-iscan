"""The grounding check of extraction (spec F3): code, not the model, decides what is kept.

A value is kept only when
- its quote is at most 300 characters,
- the quote is found in the stored redacted text of the cited source, after Unicode (NFKC),
  whitespace and typography normalisation (quotes, apostrophes, dashes), and
- the quote is long enough to carry evidence (`quote_long_enough`).

A kept value must also pass `value_supported`, a light guard on figures and words; a value it
rejects is counted with the invalid items, not with the grounding failures.

For a third-party source the supplier must also be named near the quote (#202): `passages` gives
the quote's surroundings, and the extraction stage looks for the names there.

Case, accents and wording are never normalised for the quote: it is verbatim. The text and the
quote are only compared; neither is logged.
"""

import bisect
import functools
import re
import unicodedata
from dataclasses import dataclass
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


def group_names(legal_name: str) -> list[str]:
    """The folded legal name of the parent group, and the same without its trailing legal forms
    ("plc", "Inc"), when that keeps at least four characters. Group words ("Group", "Holding")
    stay: they are part of what tells the group from another company (#195)."""
    words = fold(legal_name).replace(".", "").replace(",", " ").split()
    names = [" ".join(words)] if words else []
    while len(words) > 1 and words[-1] in _LEGAL_FORMS:
        words = words[:-1]
    short = " ".join(words)
    if short not in names and len(short) >= _MIN_SHORT_NAME:
        names.append(short)
    return names


def names_group(
    folded_text: str, names: list[str], host: str | None, labels: list[str] | None = None
) -> bool:
    """Whether the (folded) text holds one of the group's names as a whole word ("Amcor" is not
    "Amcorp"), or its website host or label."""
    if any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", folded_text) for name in names):
        return True
    return names_supplier(folded_text, [], host, labels)


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


_BLANK_LINE: Final = re.compile(r"\n[^\S\n]*\n")


def _paragraphs(text: str, blank_lines: bool) -> list[str]:
    """The normalised paragraphs of a stored text: its lines (an HTML page is stored one block
    per line), or, for `blank_lines` (a PDF, whose lines are layout lines), the blocks between
    blank lines."""
    parts = _BLANK_LINE.split(text) if blank_lines else text.splitlines()
    return [paragraph for paragraph in map(normalise, parts) if paragraph]


def passages(text: str, quote: str, chars: int, blank_lines: bool = False) -> list[str]:
    """The folded passage around each place of the quote in the text (#202): the quote's
    paragraph (from the start of the paragraph where the quote starts to the end of the one where
    it ends), cut to at most `chars` characters before and after the quote, whichever is shorter.
    Empty when the quote is not in the text. The names are then looked for in these passages with
    the rules of the whole text (`names_supplier`, `names_group`)."""
    return [fold(passage) for passage in printed_passages(text, quote, chars, blank_lines)]


def printed_passages(text: str, quote: str, chars: int, blank_lines: bool = False) -> list[str]:
    """`passages`, normalised but not folded: case kept, as the source prints it (#209)."""
    needle = normalise(quote)
    paragraphs = _paragraphs(text, blank_lines)
    if not needle or not paragraphs:
        return []
    joined = " ".join(paragraphs)
    starts: list[int] = []
    position = 0
    for paragraph in paragraphs:
        starts.append(position)
        position += len(paragraph) + 1
    found: list[str] = []
    start = joined.find(needle)
    while start != -1:
        end = start + len(needle)
        first = bisect.bisect_right(starts, start) - 1
        last = bisect.bisect_right(starts, end - 1) - 1
        low = max(starts[first], start - chars)
        high = min(starts[last] + len(paragraphs[last]), end + chars)
        found.append(joined[low:high])
        start = joined.find(needle, start + 1)
    return found


# --- Another entity of the group (#209) ---
#
# A passage that prints the supplier's or the group's name without its legal form, immediately
# followed by another legal form ("BERICAP GmbH & Co. KG" for the confirmed "BERICAP", France) is
# about another legal entity of the group. Case and punctuation of the legal form are ignored.

# The legal-form words of the name rules, and SASU; "Limited" and "Corporation" are "Ltd" and
# "Corp".
_FORM_WORDS: Final = _LEGAL_FORMS | {"sasu"}
_FORM_ALIASES: Final = {"limited": "ltd", "corporation": "corp"}
# Words of a legal form that are no legal form on their own ("BERICAP and Amcor").
_CONNECTORS: Final = frozenset({"&", "and", "co", "company"})
_JOINED_BY: Final = frozenset({"co", "company"})  # "&" and "and" only before these ("& Co.")
# Ordinary words of a page that are also a legal form ("Acme as a leader", "Acme se développe",
# "Acme ab 2024"): a legal form only when printed with a capital letter.
_COMMON_WORDS: Final = frozenset({"as", "se", "sa", "ab", "spa", "limited"})
# The countries where each legal form is used (ISO 3166-1 alpha-2). A form used only outside the
# supplier's country tells another entity when the confirmed legal name has no legal form; a form
# not in this table, or also used in the supplier's country, tells nothing.
_GERMANIC: Final = frozenset({"DE", "AT", "CH", "LI"})
_COMMON_LAW: Final = frozenset(
    {"GB", "IE", "AU", "NZ", "HK", "SG", "IN", "CA", "IL", "ZA", "NG", "KE", "MT", "CY", "MY"}
)
_FORM_COUNTRIES: Final[dict[str, frozenset[str]]] = {
    "gmbh": _GERMANIC,
    "ag": _GERMANIC,
    "kg": _GERMANIC,
    "ohg": _GERMANIC,
    "ug": _GERMANIC,
    "kgaa": _GERMANIC,
    "sas": frozenset({"FR", "CO"}),
    "sasu": frozenset({"FR"}),
    "sarl": frozenset({"FR", "LU", "CH", "MA", "TN", "DZ", "LB", "SN", "CI", "CM", "MC"}),
    "eurl": frozenset({"FR", "DZ"}),
    "snc": frozenset({"FR", "IT", "LU", "MA", "TN", "DZ", "MC"}),
    "bv": frozenset({"NL", "BE"}),
    "nv": frozenset({"NL", "BE", "CW", "SX", "SR", "AW"}),
    "spa": frozenset({"IT", "CL", "SM"}),
    "srl": frozenset({"IT", "BE", "RO", "MD", "AR", "PE", "SM", "BO", "CR", "DO", "UY", "VE"}),
    "sl": frozenset({"ES"}),
    "ltd": _COMMON_LAW,
    "plc": frozenset({"GB", "IE", "NG", "LK"}),
    "inc": frozenset({"US", "CA", "PH"}),
    "llc": frozenset({"US", "AE", "RU", "UA", "AM", "GE", "AZ", "KZ", "OM", "QA", "SA", "BH"}),
    "corp": frozenset({"US", "CA", "PH", "JP", "TW"}),
}
_EDGE_PUNCTUATION: Final = "()[]{}\"'.,;:!?"
_RUN_ENDS: Final = tuple(",;:!?)]")
_NAME_ENDS: Final = tuple(".;:!?)]")
MAX_ENTITY_CHARS: Final = 300


def _key(token: str) -> str:
    """A token of a text as the name rules compare it: folded, edge punctuation and inner points
    removed ("S.A.S." is "sas", "(BERICAP" is "bericap")."""
    return fold(token).strip(_EDGE_PUNCTUATION).replace(".", "")


def _bare_name(legal_name: str) -> tuple[str | None, tuple[str, ...]]:
    """The folded legal name without its trailing legal forms (None when that leaves fewer than
    four characters), and those legal forms, without the connectors ("GmbH & Co. KG" gives
    ("gmbh", "kg"))."""
    words = fold(legal_name).replace(".", "").replace(",", " ").split()
    forms: list[str] = []
    while len(words) > 1 and words[-1] in _FORM_WORDS:
        word = _FORM_ALIASES.get(words[-1], words[-1])
        if word not in _CONNECTORS:
            forms.insert(0, word)
        words = words[:-1]
    bare = " ".join(words)
    return (bare if len(bare) >= _MIN_SHORT_NAME else None), tuple(forms)


@dataclass(frozen=True)
class NamedCompany:
    """A company printed in a text as a known name followed by a legal form."""

    name: str  # the folded bare name it was found by
    forms: tuple[str, ...]  # its legal forms, connectors left out
    printed: str  # name and legal form as the text prints them


def _form_at(tokens: list[str], keys: list[str], at: int) -> tuple[str, int] | None:
    """The legal-form word starting at token `at`, and the number of tokens it takes ("S. A. S."
    takes three), or None."""
    key = keys[at]
    if key in _FORM_WORDS:
        if key in _COMMON_WORDS and not tokens[at].strip(_EDGE_PUNCTUATION)[:1].isupper():
            return None
        return _FORM_ALIASES.get(key, key), 1
    if len(key) == 1 and key.isalpha():
        for width in (4, 3, 2):
            part = keys[at : at + width]
            joined = "".join(part)
            if len(part) == width and all(len(k) == 1 for k in part) and joined in _FORM_WORDS:
                return joined, width
    return None


def _form_run(tokens: list[str], keys: list[str], start: int) -> tuple[tuple[str, ...], int]:
    """The legal forms printed from token `start` on, and the index after the last real legal
    form of the run (`start` when there is none)."""
    forms: list[str] = []
    at, end = start, start
    while at < len(tokens):
        found = _form_at(tokens, keys, at)
        if found is None:
            break
        word, width = found
        if word in {"&", "and"} and (at + 1 >= len(keys) or keys[at + 1] not in _JOINED_BY):
            break
        at += width
        if word not in _CONNECTORS:
            forms.append(word)
            end = at
        if tokens[at - 1].endswith(_RUN_ENDS):
            break
    return tuple(forms), end


def named_companies(text: str, names: list[str]) -> list[NamedCompany]:
    """The companies the (normalised, not folded) text prints as one of the folded bare `names`,
    as whole words, immediately followed by a legal form; a comma may stand between them
    ("Acme, Inc."). A bare name ("BERICAP opened a plant"), or a name followed by a run of
    connectors only ("BERICAP and Amcor"), is no such company."""
    tokens = text.split()
    keys = [_key(token) for token in tokens]
    wanted = sorted({tuple(name.split()) for name in names if name}, key=len, reverse=True)
    found: list[NamedCompany] = []
    at = 0
    while at < len(tokens):
        name = next((words for words in wanted if tuple(keys[at : at + len(words)]) == words), None)
        if name is None:
            at += 1
            continue
        after = at + len(name)
        if tokens[after - 1].endswith(_NAME_ENDS):
            at = after
            continue
        forms, end = _form_run(tokens, keys, after)
        if forms:
            printed = " ".join(tokens[at:end]).strip(_EDGE_PUNCTUATION.replace(".", ""))
            if printed.endswith(".") and tokens[end - 1].count(".") == 1 and len(keys[end - 1]) > 1:
                printed = printed[:-1]  # the end of a sentence ("KG."), not of "S.A.S."
            found.append(NamedCompany(" ".join(name), forms, printed[:MAX_ENTITY_CHARS]))
        at = max(after, end)
    return found


@dataclass(frozen=True)
class GroupEntities:
    """Tells, for an identity with a parent group, whether a passage is about another entity of
    the group (#209). Built by `group_entities`."""

    entity_name: str | None
    entity_forms: tuple[str, ...]
    group_legal_name: str
    group_name: str | None
    group_forms: tuple[str, ...]
    country: str | None

    def _names(self) -> list[str]:
        return [name for name in (self.entity_name, self.group_name) if name]

    def is_other(self, company: NamedCompany) -> bool:
        """Another entity when its legal form is not the confirmed entity's: (a) the confirmed
        legal name ends in another legal form; (b) it has none, and every legal form printed is
        in the table and used only in countries other than the supplier's. Otherwise, no
        conclusion: not another entity."""
        if self.entity_forms:
            return company.forms != self.entity_forms
        if not self.country:
            return False
        countries = [_FORM_COUNTRIES.get(form) for form in company.forms]
        return all(c is not None and self.country not in c for c in countries)

    def label(self, company: NamedCompany) -> str:
        """The group's legal name when the company is the parent group, otherwise the company as
        printed in the source."""
        if company.name == self.group_name and company.forms == self.group_forms:
            return self.group_legal_name[:MAX_ENTITY_CHARS]
        return company.printed

    def other_entity(self, quote: str, printed: list[str]) -> str | None:
        """The label name of the other entity of the group the quote is about, or None. The quote
        decides: a quote naming another entity is about the first it names; a quote naming the
        supplier (with its own, or an inconclusive, legal form) and no other entity is the
        entity's; a quote naming neither is about the first other entity of its passages."""
        names = self._names()
        in_quote = named_companies(normalise(quote), names)
        for company in in_quote:
            if self.is_other(company):
                return self.label(company)
        if any(company.name == self.entity_name for company in in_quote):
            return None
        for passage in printed:
            for company in named_companies(passage, names):
                if self.is_other(company):
                    return self.label(company)
        return None


@functools.lru_cache(maxsize=64)
def group_entities(legal_name: str, group_legal_name: str, country: str | None) -> GroupEntities:
    """The rules of `GroupEntities` for one identity (cached: built once per run)."""
    entity_name, entity_forms = _bare_name(legal_name)
    group_name, group_forms = _bare_name(group_legal_name)
    return GroupEntities(
        entity_name,
        entity_forms,
        group_legal_name,
        group_name,
        group_forms,
        country.strip().upper() if country else None,
    )


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
