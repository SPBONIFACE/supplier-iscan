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

from app.redaction import lowercase, names
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
    return token[0].isupper() and key not in _ROLES and key not in names.ROLES_EXTRA


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
        """NER on the text and on a case-restored copy, widened and joined by the name rules.

        A detected span with weak evidence is dropped: one model only, and either an ALL-CAPS
        phrase (a heading) or a lone word at the start of a sentence, in a list of capitalised
        words or after "in" / "near" (a city, an ordinary word), with no honorific, label or
        closing right before it.
        """
        hits = self._ner_hits(text)
        restored = names.restore_case(text)
        if restored != text:
            hits.extend(self._ner_hits(restored))
        protected = names.protected_spans(text)
        clues = names.clue_ends(text)
        widened = [(names.extend(text, hit.span), hit) for hit in hits]
        spans: list[Span] = []
        for span in {item[0] for item in widened}:
            if _short_acronym(text, span) or any(
                span[0] < end and start < span[1] for start, end in protected
            ):
                continue
            support = {
                hit.model
                for other, hit in widened
                if hit.clean and other[0] < span[1] and span[0] < other[1]
            }
            if _weak(text, span, clues, len(support)):
                continue
            spans.append(span)
        strong, to_confirm = lowercase.spans(text)
        spans.extend(strong)
        spans.extend(span for span in to_confirm if self._looks_like_a_name(text, span))
        return [*spans, *names.rule_spans(text)]

    def _looks_like_a_name(self, text: str, span: Span) -> bool:
        """Whether a model takes the lower-case words after a label for a person once they are
        capitalised ("contact: jean dupont" yes, "contact: reception desk" no)."""
        start = max(text.rfind("\n", 0, span[0]) + 1, span[0] - 200)
        end = text.find("\n", span[1])
        end = min(len(text) if end < 0 else end, span[1] + 200)
        window = lowercase.capitalised_copy(text[start:end], (span[0] - start, span[1] - start))
        low, high = span[0] - start, span[1] - start
        votes = sum(
            any(
                entity.label_ in _PERSON_LABELS
                and entity.start_char < high
                and low < entity.end_char
                for entity in self._models[key](window).ents
            )
            for key, _ in _LATIN_MODELS
        )
        return votes >= 2

    def _ner_hits(self, text: str) -> list["_Hit"]:
        hits: list[_Hit] = []
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
                        span = (offset + cleaned[0], offset + cleaned[1])
                        hits.append(_Hit(span, key, not _has_lower_word(entity.text)))
        return hits


@dataclass(frozen=True)
class _Hit:
    """A person span found by one model; `clean` is False when the model's entity held ordinary
    lower-case words (it then says little about the span)."""

    span: Span
    model: str
    clean: bool


def _has_lower_word(entity: str) -> bool:
    return any(
        token[0].islower() and _key(token) not in _PARTICLES
        for token in entity.split()
        if token[0].isalpha()
    )


def _weak(text: str, span: Span, clues: set[int], support: int) -> bool:
    """Whether a detected span is too weak to redact without more evidence.

    `support`: how many models found it, not counting a model whose entity held ordinary
    lower-case words ("Angebot wurde von"). A clue right before it (honorific, label, closing)
    makes it strong. Without a clue, the evidence needed grows with the risk that the span is an
    ordinary word: a phrase of several words stands as it is; a lone word needs two models, and
    three at the start of a sentence, in a list of capitalised words or after "in" / "near" (a
    city, a common noun); so does a word in a line written entirely in capitals (a heading).
    """
    if names.after_clue(text, span[0], clues) or _CJK.search(text[span[0] : span[1]]):
        return False
    words = names.name_word_count(text, span)
    if words == 0:
        return False
    if names.is_heading_like(text, span):
        return not names.is_whole_line(text, span) or words > 2 or support < 3
    if names.has_stopword(text, span):
        return support < 3
    loose = names.loose_position(text, span, single=words == 1)
    if words > 1:
        return loose and support < 2
    return support < (3 if loose else 2)


def _other_pipes(package: str) -> list[str]:
    """Every pipe except `ner`, read from the package metadata (no network, no download)."""
    pipeline: list[str] = cast(dict[str, Any], spacy_info(package, silent=True))["pipeline"]
    return [name for name in pipeline if name != "ner"]


_REDACTOR = Redactor()


def get_redactor() -> Redactor:
    """The process-wide redactor: models are loaded once, on first use (or at start-up)."""
    return _REDACTOR
