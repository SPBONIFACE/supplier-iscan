"""Detection and removal of personal data (#19): email, phone, people's names, forced names.

What is removed, each omission replaced by `[…]`:
- email addresses (regex, obfuscated forms included);
- phone numbers (`phonenumbers`, with guards so that SIREN, LEI and VAT numbers survive);
- people's names: GLiNER (`detector.py`) on the text and on a case-restored copy, united with
  spaCy `zh` for text with Han characters, widened over adjacent name tokens, plus precise rules
  (honorifics, labels, table columns, lower-case clues; `names.py`, `lowercase.py`);
- names the caller forces (suppression entries, the confirmed name and registered address of a
  natural person), matched ignoring case and accents, whatever the detection found.

A company's name survives when a model mislabels it: spans with a legal form or company word, and
spans inside a registry company name the caller lists in `keep`, are not redacted (forced names
always win over `keep`). Models are loaded once per process, never fetched. The text itself is
never logged and never put in an exception message. Any failure is `RedactionUnavailable`.
"""

import logging
import re
import threading
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

import phonenumbers

from app.redaction import lowercase, names
from app.redaction.detector import (
    GlinerDetector,
    NameDetector,
    SpacyHanDetector,
    has_han,
    strip_cjk,
)
from app.redaction.text import OMISSION, RedactedText, RedactionUnavailable, mint

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS: Final = 4_000_000
_PHONE_REGIONS: Final = ("FR", "DE", "GB", "US", "ES", "IT")

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+%-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
_TOKEN = re.compile(r"\S+")
_ID_LABEL = re.compile(
    r"(siren|siret|lei|vat|tva|ust|uid|nif|cif|hrb|hra|duns|isin|iban|ein|reg|n°|nº|no\.?|nr\.?|"
    r"num(?:ber|éro|mer|ero|ero)?|número|iva|rcs|registro|tomo)[\s:.\-#]*(?:[a-z]{2}\s*)?$",
    re.IGNORECASE,
)
_PHONE_WORD = re.compile(
    r"(?:tel|phone|mobile|handy|fax|cell|call|rufnummer|appel|llam|chiam|portable|whatsapp)",
    re.IGNORECASE,
)
_NAME_GAP = r"[\s,\-‐-―]+"


def fold(text: str) -> tuple[str, list[int]]:
    """Lower case without accents, and for each folded character its index in `text`."""
    out: list[str] = []
    index: list[int] = []
    for position, char in enumerate(text):
        for piece in unicodedata.normalize("NFKD", char):
            if unicodedata.combining(piece):
                continue
            for lowered in piece.casefold():
                out.append(lowered)
                index.append(position)
    return "".join(out), index


_ROLES = names.ROLES
_JOINERS = frozenset("and et und y e of &".split())
_PARTICLES = frozenset(
    "von van der den de del della di da dos du la le bin al el ben ter ten zu zur af".split()
)
_COMPANY_WORDS = frozenset(
    """sa sas sasu sarl eurl sci gmbh ag kg ohg se ug ltd limited llc llp lp inc corp corporation
    plc bv nv spa srl sl slu ab oy as aps co company holding holdings group gruppe groupe bank
    partners industries technologies solutions services components logistics textiles systems
    manufacturing supplies trading capital energy steel""".split()
)


def _name_pattern(name: str, gap: str = _NAME_GAP) -> re.Pattern[str] | None:
    folded, _ = fold(name)
    tokens = [re.escape(token) for token in re.split(gap, folded) if token]
    if not tokens:
        return None
    return re.compile(r"(?<!\w)" + gap.join(tokens) + r"(?!\w)", re.UNICODE)


def _variants(name: str) -> list[str]:
    """The name, and its German transliteration (Müller written Mueller)."""
    table = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})
    transliterated = name.translate(table)
    return [name] if transliterated == name else [name, transliterated]


# Groups of equivalent street words and their common abbreviations (folded, no dots): "rue" and
# "r", "Straße" and "Str.", "Street" and "St". A token of the stored address matches any member of
# its groups in the text. Other abbreviations are not matched.
_ABBREVIATIONS: Final = tuple(
    frozenset(group.split())
    for group in (
        "street st str",
        "road rd",
        "lane ln",
        "drive dr",
        "court ct",
        "square sq",
        "avenue av ave",
        "boulevard bd bvd blvd",
        "saint st",
        "sainte ste",
        "number no nr n",
        "rue r",
        "chemin ch",
        "place pl",
        "route rte",
        "impasse imp",
        "allee all",
        "quai q",
        "strasse str",
        "platz pl",
        "calle c cl",
        "avenida av avda",
        "plaza pza pl",
        "paseo pso",
        "via v",
        "viale vle",
        "piazza pza p",
        "corso cso c",
        "strada str",
    )
)
_ADDRESS_GAP: Final = r"[\W_]+"
_ADDRESS_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_MAX_ADDRESS_PARTS: Final = 6


def _address_slices(address: str) -> list[str]:
    """The whole address, and every run of its comma-separated parts that holds a digit and is
    long enough to be an address (so a mention without the country, or the postcode and city
    alone, is found)."""
    parts = [part.strip() for part in address.split(",") if part.strip()][:_MAX_ADDRESS_PARTS]
    slices = [address.strip()]
    for first in range(len(parts)):
        for last in range(first + 1, len(parts) + 1):
            piece = ", ".join(parts[first:last])
            if len(piece) >= 6 and any(char.isdigit() for char in piece) and piece not in slices:
                slices.append(piece)
    return slices


def _address_pattern(address: str) -> re.Pattern[str] | None:
    """A pattern for an address on folded text: ignores case, accents, spacing, punctuation and
    line breaks, and accepts the abbreviation variants of `_ABBREVIATIONS` ("rue"/"r.",
    "Straße"/"Str.", "Hauptstraße"/"Hauptstr.", "Street"/"St")."""
    folded, _ = fold(address)
    tokens = _ADDRESS_TOKEN.findall(folded)
    if not tokens:
        return None
    pieces: list[str] = []
    for token in tokens:
        alternatives = {token}
        for group in _ABBREVIATIONS:
            if token in group:
                alternatives |= group
        if len(token) > 7 and token.endswith("strasse"):
            alternatives.add(token[: -len("strasse")] + "str")
        elif len(token) > 4 and token.endswith("str"):
            alternatives.add(token[: -len("str")] + "strasse")
        ordered = sorted(alternatives, key=len, reverse=True)
        pieces.append("(?:" + "|".join(re.escape(item) for item in ordered) + ")")
    return re.compile(r"(?<![^\W_])" + _ADDRESS_GAP.join(pieces) + r"(?![^\W_])", re.UNICODE)


@dataclass(frozen=True)
class RedactionContext:
    """What the caller knows about the text it redacts.

    - `names`: people's names to always redact (suppression entries, a natural person's confirmed
      legal name);
    - `addresses`: addresses to always redact (a natural person's registered address);
    - `keep`: company names (registry legal names of companies, never of a natural person) that
      NER must not redact.
    """

    names: tuple[str, ...] = ()
    addresses: tuple[str, ...] = ()
    keep: tuple[str, ...] = ()


Span = tuple[int, int]


def _email_spans(text: str) -> list[Span]:
    return [match.span() for match in _EMAIL.finditer(text)]


_AT = r"[\[\(\{<]\s*(?:at|arobase)\s*[\]\)\}>]"
_DOT_WORD = r"(?:\s*[\[\(\{<]\s*(?:dot|point|punkt)\s*[\]\)\}>]\s*|[ \t]+(?:dot|point|punkt)[ \t]+)"
_LABEL = r"[^\W_][\w-]*"
_OBFUSCATED_BRACKET = re.compile(
    rf"(?<![\w.+-])[\w.+%-]+[ \t]*{_AT}[ \t]*{_LABEL}(?:(?:{_DOT_WORD}|\.){_LABEL})+(?![\w-])",
    re.IGNORECASE,
)
# "jean at acme dot com": the bare word "at" (an ordinary word) counts only as the shape
# `word at word dot tld`, the domain spelt with "dot" and ending in a known top-level domain, and
# a first word that is not an ordinary function word or a verb that takes "at" ("look at acme
# dot com"). "arobase", "arroba" and "chiocciola" are never ordinary words.
_OBFUSCATED_BARE = re.compile(
    rf"(?<![\w.+-])(?P<local>[\w.+%-]+)[ \t]+(?P<at>at|arobase|arroba|chiocciola)[ \t]+"
    rf"(?P<domain>{_LABEL}(?:\.{_LABEL})*{_DOT_WORD}{_LABEL}(?:(?:{_DOT_WORD}|\.){_LABEL})*)"
    rf"(?![\w-])",
    re.IGNORECASE,
)
_TLDS = frozenset(
    """com org net edu gov int info biz eu fr de es it uk nl be ch us ca io co pt se dk fi pl
    ie cn jp ru br au nz cz gr tr""".split()
)
_AT_VERBS = frozenset(
    """look looks looked looking stare glance arrive arrives arrived meet meets stay stays wait
    waits aim aims shop shops work works worked working point points laugh smile guess marvel
    excel start starts begin begins available found located visit see check read buy order
    shown listed hosted online""".split()
)
_DOT_SPLIT = re.compile(
    r"\s*[\[\(\{<]\s*(?:dot|point|punkt)\s*[\]\)\}>]\s*|[ \t]+(?:dot|point|punkt)[ \t]+|\.",
    re.IGNORECASE,
)


def _bare_email_ok(match: re.Match[str]) -> bool:
    last = _DOT_SPLIT.split(match.group("domain"))[-1].casefold()
    if last not in _TLDS:
        return False
    if match.group("at").casefold() != "at":
        return True
    local = fold(match.group("local"))[0]
    return local not in names.FUNCTION_WORDS and local not in _AT_VERBS


def _obfuscated_email_spans(text: str) -> list[Span]:
    spans = [match.span() for match in _OBFUSCATED_BRACKET.finditer(text)]
    spans.extend(match.span() for match in _OBFUSCATED_BARE.finditer(text) if _bare_email_ok(match))
    return spans


def _phone_spans(text: str) -> list[Span]:
    spans: dict[Span, bool] = {}
    for region in (None, *_PHONE_REGIONS):
        matcher = phonenumbers.PhoneNumberMatcher(
            text, region, leniency=phonenumbers.Leniency.VALID, max_tries=200
        )
        for match in matcher:
            raw = text[match.start : match.end]
            if _accept_phone(text, match.start, match.end, raw):
                spans[(match.start, match.end)] = True
    return list(spans)


def _accept_phone(text: str, start: int, end: int, raw: str) -> bool:
    """Guards against identifiers: SIREN, SIRET, LEI, VAT and revenue figures stay."""
    if start > 0 and (text[start - 1].isalnum()) or end < len(text) and text[end].isalnum():
        return False
    if raw.startswith(("+", "00")):
        return True
    if _ID_LABEL.search(text[max(0, start - 14) : start]) and not _PHONE_WORD.search(
        text[max(0, start - 40) : start]
    ):
        return False
    # Without an international prefix: a national trunk "0", or a bracketed / dashed grouping.
    return raw.startswith(("0", "(")) or "-" in raw


def _forced_spans(text: str, context: RedactionContext) -> list[Span]:
    folded, index = fold(text)
    spans: list[Span] = []
    patterns = [_name_pattern(name) for raw in context.names for name in _variants(raw)]
    patterns.extend(
        _address_pattern(piece)
        for address in context.addresses
        for part in _address_slices(address)
        for piece in _variants(part)
    )
    for pattern in patterns:
        if pattern is None:
            continue
        for match in pattern.finditer(folded):
            spans.append((index[match.start()], index[match.end() - 1] + 1))
    return spans


def _key(token: str) -> str:
    folded = fold(token.strip(".,;:()[]{}\"'"))[0].replace(".", "")
    return re.split("['\u2019]", folded)[-1]


def _is_legal_form(token: str) -> bool:
    """A legal form or company word. An ambiguous short word ("as", "se", "co") counts only when
    it is not written in plain lower case; a dotted form ("S.p.A.", "s.r.l.") always counts."""
    dotted = token.strip(",;:()[]{}\"'")
    if _DOTTED_FORM.fullmatch(dotted if dotted.endswith(".") else dotted + "."):
        return True  # an initialism written with dots: S.p.A., S.r.l.s., S.L.U., e.V.
    if _key(token) not in _COMPANY_WORDS:
        return False
    bare = token.strip(".,;:()[]{}\"'")
    return "." in bare or bare != bare.lower() or len(bare) > 3


_DOTTED_FORM = re.compile(r"(?:[^\W\d_]\.){2,}")


def _carries_legal_form(text: str, span: Span) -> bool:
    """A name-shaped phrase that carries a legal form is a company: the legal form is inside the
    span, or follows it on the same line after capitalised words ("Brackley Precision Ltd")."""
    end = span[1]
    while end < len(text) and not text[end].isspace():
        end += 1  # a model can cut inside a token ("S.p" of "S.p.A.")
    if any(_is_legal_form(token) for token in text[span[0] : end].split()):
        return True
    if any(char in ",;:.!?" for char in text[span[1] : end]):
        # the phrase ends at a comma or a full stop: only a legal form may follow, and only after
        # a comma ("Villalba Fundiciones, S.A."), never in the next sentence
        if "," not in text[span[1] : end]:
            return False
        following = _TOKEN.match(text, _skip_space(text, end))
        return following is not None and _is_legal_form(following.group())
    position = _skip_space(text, end)
    for _ in range(5):
        following = _TOKEN.match(text, position)
        if following is None:
            return False
        word = following.group()
        if _is_legal_form(word):
            return True
        if word[-1] in ",;:" or not (
            word[0].isupper() or word == "&" or _key(word) in _PARTICLES | _JOINERS
        ):
            return False
        position = _skip_space(text, following.end())
    return False


def _is_company(text: str, span: Span, keep_keys: Sequence[str]) -> bool:
    if _carries_legal_form(text, span):
        return True
    folded = " ".join(fold(text[span[0] : span[1]])[0].split())
    return any(f" {folded} " in f" {kept} " for kept in keep_keys)


def _skip_space(text: str, position: int) -> int:
    while position < len(text) and text[position] in " \t":
        position += 1
    return position


def _merge(spans: Iterable[Span], text: str) -> list[Span]:
    """Overlapping spans, and spans separated only by blanks, become one omission."""
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and (start <= merged[-1][1] or not text[merged[-1][1] : start].strip()):
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


class Redactor:
    """Loads the detectors once per process and redacts text.

    `detector` and `han_detector` are injected by tests (a small fake); in the application they
    are GLiNER and spaCy `zh`, built and loaded on first use.
    """

    def __init__(
        self, detector: NameDetector | None = None, han_detector: NameDetector | None = None
    ) -> None:
        self._detector = detector
        self._han_detector = han_detector
        self._lock = threading.Lock()
        self._loaded = detector is not None

    def load(self) -> None:
        """Load the models (idempotent). Raises RedactionUnavailable when one is missing."""
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                gliner = GlinerDetector()
                gliner.load()
                han = SpacyHanDetector()
                han.load()
            except Exception as error:  # noqa: BLE001 - any load failure is fail-closed
                logger.error("Redaction models could not be loaded: %s", type(error).__name__)
                raise RedactionUnavailable from None
            self._detector, self._han_detector = gliner, han
            self._loaded = True

    def redact(self, text: str, context: RedactionContext | None = None) -> RedactedText:
        context = context or RedactionContext()
        try:
            return mint(self._redact(text, context))
        except RedactionUnavailable:
            raise
        except Exception as error:  # noqa: BLE001 - fail closed, never a fallback
            logger.error("Redaction failed: %s", type(error).__name__)
            raise RedactionUnavailable from None

    def _redact(self, text: str, context: RedactionContext) -> str:
        if not text:
            return text
        out: list[str] = []
        position = 0
        for start, end in self.removed_spans(text, context):
            out.append(text[position:start])
            out.append(OMISSION)
            position = end
        out.append(text[position:])
        return "".join(out)

    def removed_spans(self, text: str, context: RedactionContext | None = None) -> list[Span]:
        """The merged character spans that `redact` replaces (also used by the measure script)."""
        context = context or RedactionContext()
        if not text:
            return []
        if len(text) > MAX_TEXT_CHARS:
            logger.error("Redaction refused a text over %d characters", MAX_TEXT_CHARS)
            raise RedactionUnavailable
        self.load()
        keep_keys = [" ".join(fold(name)[0].split()) for name in context.keep]
        spans = [
            *_email_spans(text),
            *_obfuscated_email_spans(text),
            *_phone_spans(text),
            *_forced_spans(text, context),
        ]
        for span in self._person_spans(text):
            if not _is_company(text, span, keep_keys):
                spans.append(span)
        return _merge(spans, text)

    def _person_spans(self, text: str) -> list[Span]:
        """Detector spans (text and case-restored copy; plus `zh` for Han text), widened over
        adjacent name tokens, then the rules. A failure of any model call propagates."""
        detector = self._detector
        if detector is None:
            raise RedactionUnavailable
        copy = names.case_restored_copy(text)
        batch = [text] if copy == text else [text, copy]
        found = [span for spans in detector.person_spans(batch) for span in spans]
        if has_han(text) and self._han_detector is not None:
            for span in self._han_detector.person_spans([text])[0]:
                cleaned = strip_cjk(text, span)
                if cleaned:
                    found.append(cleaned)
        spans = [names.extend(text, span) for span in set(found)]
        base, to_confirm = lowercase.spans(text)
        spans.extend(base)
        spans.extend(self._confirmed(text, to_confirm))
        return [*spans, *names.rule_spans(text)]

    def _confirmed(self, text: str, candidates: list[Span]) -> list[Span]:
        """Lower-case words after a label that the detector takes for a person once they are
        capitalised ("contact: jean dupont" yes, "contact: reception desk" no)."""
        if not candidates or self._detector is None:
            return []
        windows: list[tuple[str, Span]] = []
        for span in candidates:
            start = max(text.rfind("\n", 0, span[0]) + 1, span[0] - 200)
            end = text.find("\n", span[1])
            end = min(len(text) if end < 0 else end, span[1] + 200)
            window = lowercase.capitalised_copy(text[start:end], (span[0] - start, span[1] - start))
            windows.append((window, (span[0] - start, span[1] - start)))
        found = self._detector.person_spans([window for window, _ in windows])
        return [
            span
            for span, (_, (low, high)), hits in zip(candidates, windows, found, strict=True)
            if any(start < high and low < end for start, end in hits)
        ]


_REDACTOR = Redactor()


def get_redactor() -> Redactor:
    """The process-wide redactor: models are loaded once, on first use."""
    return _REDACTOR
