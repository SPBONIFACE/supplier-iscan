"""Detection and removal of personal data (#19): email, phone, people's names, forced names.

What is removed, each omission replaced by `[…]`:
- email addresses (regex);
- phone numbers (`phonenumbers`, with guards so that SIREN, LEI and VAT numbers survive);
- people's names found by spaCy NER (`en`, `de` and the multilingual `xx` model, united: recall
  first; `zh` when the text has Han characters), cleaned of roles and company words;
- names the caller forces (suppression entries, the confirmed name and registered address of a
  natural person), matched ignoring case and accents, whatever the detection found.

A company's name survives when NER mislabels it: spans with a legal form or company word, and
spans inside a registry company name the caller lists in `keep`, are not redacted (forced names
always win over `keep`). Models are loaded once per process, only the `ner` pipe, never fetched.
The text itself is never logged and never put in an exception message.
"""

import logging
import re
import threading
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, cast

import phonenumbers
import spacy
from spacy.cli.info import info as spacy_info

from app.redaction import names
from app.redaction.text import OMISSION, RedactedText, RedactionUnavailable, mint

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS: Final = 4_000_000
CHUNK_CHARS: Final = 20_000
_LATIN_MODELS: Final = (
    ("en", "en_core_web_sm"),
    ("de", "de_core_news_sm"),
    ("xx", "xx_ent_wiki_sm"),
)
_HAN_MODEL: Final = ("zh", "zh_core_web_sm")
_PERSON_LABELS: Final = {"PERSON", "PER"}
_PHONE_REGIONS: Final = ("FR", "DE", "GB", "US", "ES", "IT")

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+%-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
_HAN = re.compile(r"[㐀-鿿豈-﫿]")
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯豈-﫿]")
_TOKEN = re.compile(r"\S+")
_ID_LABEL = re.compile(
    r"(siren|siret|lei|vat|tva|ust|uid|nif|cif|hrb|hra|duns|isin|iban|ein|reg|n°|no\.?)[\s:.\-#]*$",
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


def _address_parts(address: str) -> list[str]:
    parts = [part.strip() for part in address.split(",")]
    lines = [part for part in parts if len(part) >= 6 and any(c.isdigit() for c in part)]
    return [address.strip(), *lines]


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
# "jean at acme dot com": the bare word "at" counts only when the domain is spelt with "dot".
_OBFUSCATED_BARE = re.compile(
    rf"(?<![\w.+-])[\w.+%-]+[ \t]+(?:at|arobase)[ \t]+{_LABEL}(?:\.{_LABEL})*{_DOT_WORD}{_LABEL}"
    rf"(?:(?:{_DOT_WORD}|\.){_LABEL})*(?![\w-])",
    re.IGNORECASE,
)


def _obfuscated_email_spans(text: str) -> list[Span]:
    return [
        match.span()
        for pattern in (_OBFUSCATED_BRACKET, _OBFUSCATED_BARE)
        for match in pattern.finditer(text)
    ]


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
    if _ID_LABEL.search(text[max(0, start - 14) : start]):
        return False
    # Without an international prefix: a national trunk "0", or a bracketed / dashed grouping.
    return raw.startswith(("0", "(")) or "-" in raw


def _forced_spans(text: str, context: RedactionContext) -> list[Span]:
    folded, index = fold(text)
    spans: list[Span] = []
    entries = [name for raw in context.names for name in _variants(raw)]
    for address in context.addresses:
        entries.extend(_address_parts(address))
    for entry in entries:
        pattern = _name_pattern(entry)
        if pattern is None:
            continue
        for match in pattern.finditer(folded):
            spans.append((index[match.start()], index[match.end() - 1] + 1))
    return spans


def _key(token: str) -> str:
    folded = fold(token.strip(".,;:()[]{}\"'"))[0].rstrip(".")
    return re.split("['\u2019]", folded)[-1]


def _clean_person(text: str, start: int, end: int) -> Span | None:
    """Trim roles, honorifics and trailing words off a detected span; None when nothing is left."""
    span = text[start:end]
    if _CJK.search(span):
        stripped = span.strip(" \t\n,.;:()")
        if not stripped:
            return None
        offset = start + span.index(stripped)
        return offset, offset + len(stripped)
    tokens = list(_TOKEN.finditer(span))
    first, last = 0, len(tokens)
    while first < last and _is_lead_noise(tokens[first].group()):
        first += 1
    stop = first
    while stop < last and _is_name_token(tokens[stop].group()):
        stop += 1
    while stop > first and (
        _key(tokens[stop - 1].group()) in _ROLES or _key(tokens[stop - 1].group()) in _PARTICLES
    ):
        stop -= 1
    if stop <= first:
        return None
    new_start = start + tokens[first].start()
    new_end = start + tokens[stop - 1].end()
    cleaned = text[new_start:new_end].rstrip(",.;:)(\"'")
    if not cleaned or any(c.isdigit() for c in cleaned):
        return None
    return new_start, new_start + len(cleaned)


def _is_lead_noise(token: str) -> bool:
    key = _key(token)
    if not key or key in _ROLES or not token[0].isupper():
        return True
    return names.not_a_name(names.fold(token.strip(".,;:()[]{}\"'")).rstrip("."), common=True)


def _short_acronym(text: str, span: Span) -> bool:
    """A lone ALL-CAPS word of four letters or fewer ("GRI", "IVA") is an acronym, not a name."""
    inside = text[span[0] : span[1]]
    return len(inside) <= 4 and inside.isalpha() and inside.isupper()


def _is_name_token(token: str) -> bool:
    key = _key(token)
    if key in _PARTICLES:
        return True
    return token[0].isupper() and key not in _ROLES


def _is_company(text: str, span: Span, keep_keys: Sequence[str]) -> bool:
    inside = text[span[0] : span[1]]
    keys = {_key(token) for token in inside.split()}
    if keys & _COMPANY_WORDS:
        return True
    following = _TOKEN.match(text, _skip_space(text, span[1]))
    if following and _key(following.group()) in _COMPANY_WORDS:
        return True
    folded = " ".join(fold(inside)[0].split())
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


def _chunks(text: str) -> list[tuple[int, str]]:
    """Pieces of at most CHUNK_CHARS, cut at a line break, a full stop or a space."""
    pieces: list[tuple[int, str]] = []
    position = 0
    while position < len(text):
        end = min(position + CHUNK_CHARS, len(text))
        if end < len(text):
            for separator in ("\n", ". ", " "):
                cut = text.rfind(separator, position + CHUNK_CHARS // 2, end)
                if cut != -1:
                    end = cut + len(separator)
                    break
        pieces.append((position, text[position:end]))
        position = end
    return pieces


@dataclass
class Redactor:
    """Loads the NER models once per process and redacts text."""

    _models: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _loaded: bool = field(default=False, init=False)

    def load(self) -> None:
        """Load the models (idempotent). Raises RedactionUnavailable when one is missing."""
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                for key, package in (*_LATIN_MODELS, _HAN_MODEL):
                    nlp = spacy.load(package, exclude=_other_pipes(package))
                    nlp.max_length = CHUNK_CHARS * 2
                    self._models[key] = nlp
            except Exception as error:  # noqa: BLE001 - any load failure is fail-closed
                self._models.clear()
                logger.error("Redaction models could not be loaded: %s", type(error).__name__)
                raise RedactionUnavailable from None
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
        out: list[str] = []
        position = 0
        for start, end in _merge(spans, text):
            out.append(text[position:start])
            out.append(OMISSION)
            position = end
        out.append(text[position:])
        return "".join(out)

    def _person_spans(self, text: str) -> list[Span]:
        """NER on the text and on a case-restored copy, widened and joined by the name rules."""
        found = self._ner_spans(text)
        restored = names.restore_case(text)
        if restored != text:
            found.extend(self._ner_spans(restored))
        protected = names.protected_spans(text)
        spans = [
            span
            for span in (names.extend(text, found_span) for found_span in found)
            if not _short_acronym(text, span)
            and not any(span[0] < end and start < span[1] for start, end in protected)
        ]
        return [*spans, *names.rule_spans(text)]

    def _ner_spans(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for offset, chunk in _chunks(text):
            keys = [key for key, _ in _LATIN_MODELS]
            if _HAN.search(chunk):
                keys.append(_HAN_MODEL[0])
            for key in keys:
                for entity in self._models[key](chunk).ents:
                    if entity.label_ not in _PERSON_LABELS:
                        continue
                    cleaned = _clean_person(chunk, entity.start_char, entity.end_char)
                    if cleaned:
                        spans.append((offset + cleaned[0], offset + cleaned[1]))
        return spans


def _other_pipes(package: str) -> list[str]:
    """Every pipe except `ner`, read from the package metadata (no network, no download)."""
    pipeline: list[str] = cast(dict[str, Any], spacy_info(package, silent=True))["pipeline"]
    return [name for name in pipeline if name != "ner"]


_REDACTOR = Redactor()


def get_redactor() -> Redactor:
    """The process-wide redactor: models are loaded once, on first use (or at start-up)."""
    return _REDACTOR
