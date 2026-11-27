"""Chinese person names for redaction (#100): rules around the two models, in Han and romanised.

GLiNER and spaCy `zh` find about three Han names in four. This module adds precise rules, from
word lists and two data files (`data/han_surnames.txt`, `data/pinyin_surnames.txt`); no model, no
new dependency:

- `han_spans`: a name made of a surname and one or two given characters, accepted only where the
  context says "person": after a label ("联系人："), next to a title ("张经理", "总经理王浩然"),
  alone on its line or in a table cell, between a leading word and a verb ("由陈雨桐签字"), or
  written with a middle dot (minority and foreign names). A name split by a line break is read
  whole;
- `latin_spans`: a romanised name (pinyin, Hong Kong and Taiwan spellings): two to four capitalised
  or ALL-CAPS words that read as Chinese syllables, the first or the last a known surname ("Zhang
  Wei", "Wei Zhang", "ZHANG Wei", "Chan Tai Man", "Lin Yu-ting"), and a lone surname after a role
  ("Manager Li"); never when a company, product or place word follows ("Suzhou Zi Jin Plastic");
- `trim_titles`, `in_organisation`: a title word next to a name is not part of it, and a span of a
  model inside a Han company, product or place name is not a person.

Every function is pure and local; nothing here reads the network or logs the text.
"""

import re
from functools import cache
from pathlib import Path
from typing import Final

Span = tuple[int, int]

_DATA: Final = Path(__file__).parent / "data"
_H: Final = "㐀-鿿豈-﫿"
_HAN: Final = re.compile(f"[{_H}]")


def _is_han(char: str) -> bool:
    return _HAN.fullmatch(char) is not None


def _read(name: str) -> list[str]:
    lines = (_DATA / name).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


@cache
def _surnames() -> tuple[frozenset[str], frozenset[str]]:
    single: set[str] = set()
    compound: set[str] = set()
    for line in _read("han_surnames.txt"):
        for token in line.split() if " " in line else list(line):
            (single if len(token) == 1 else compound).add(token)
    return frozenset(single), frozenset(compound)


@cache
def _pinyin_surnames() -> frozenset[str]:
    return frozenset(word for line in _read("pinyin_surnames.txt") for word in line.split())


def _words(raw: str) -> tuple[str, ...]:
    return tuple(sorted(raw.split(), key=len, reverse=True))


# ---- Han ------------------------------------------------------------------------------------
@cache
def _lists() -> dict[str, list[str]]:
    """The sections of `data/han_words.txt`: name -> the lines of the section."""
    sections: dict[str, list[str]] = {}
    current: list[str] = []
    for line in _read("han_words.txt"):
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], [])
        else:
            current.append(line)
    return sections


def _section_words(name: str) -> tuple[str, ...]:
    """The words of a section, longest first."""
    return _words(" ".join(_lists()[name]))


def _section_chars(name: str) -> frozenset[str]:
    return frozenset("".join(_lists()[name]).replace(" ", ""))


TITLES_AFTER: Final = _section_words("titles_after")
TITLES_AFTER_LONG: Final = tuple(word for word in TITLES_AFTER if len(word) > 1)
TITLES_BEFORE: Final = _section_words("titles_before")
LABELS: Final = _section_words("labels")
LEFT_WORDS: Final = _section_words("left_words")
# A character that can follow a name in a sentence (a verb or a particle).
RIGHT_OK: Final = _section_chars("right_ok")
# After a middle dot only these end a name (transliterated names are full of other characters).
DOT_STOP: Final = _section_chars("dot_stop")
# Not a given-name character (function words): a name never runs into them.
GIVEN_STOP: Final = _section_chars("given_stop")
# Words that look like a surname plus a given name and are common nouns or places.
COMMON: Final = frozenset(_section_words("common"))
CITIES: Final = _section_words("cities")
# A name of a company, a product or a place ends with, or contains, one of these.
ORGANISATION: Final = _section_words("organisation")
SUFFIX_CHARS: Final = _section_chars("suffix_chars")
_RUN_STOP: Final = _section_chars("run_stop")

_LABEL_RE: Final = re.compile(
    "(?:" + "|".join(LABELS) + r"|(?i:contact(?:[ ]person)?|name|signed[ ]by|attn))"
    r"[ \t　]*[:：]?[ \t　]*\n?[ \t　]*"
)
_TITLE_AFTER_RE: Final = re.compile("|".join(TITLES_AFTER))
_TITLE_BEFORE_RE: Final = re.compile("|".join(TITLES_BEFORE))
_LEFT_RE: Final = re.compile("(?:" + "|".join((*LEFT_WORDS, *LABELS, *TITLES_BEFORE)) + ")$")
_DOT: Final = "·•・∙"
_LINE_MARKS: Final = " \t　-•*·|、"


def _surname_lengths(text: str, i: int) -> list[int]:
    single, compound = _surnames()
    lengths: list[int] = []
    if text[i : i + 2] in compound:
        lengths.append(2)
    if text[i] in single:
        lengths.append(1)
    return lengths


def _candidates(text: str, i: int, *, minimum: int = 1) -> list[Span]:
    """Names that start at `i`: a surname, a line break at most, then one or two given characters
    (`minimum` of them at least). Longest first."""
    if i >= len(text) or not _is_han(text[i]):
        return []
    found: list[Span] = []
    for length in _surname_lengths(text, i):
        j = i + length
        if j < len(text) and text[j] == "\n":
            j += 1
        given = 0
        while (
            given < 2
            and j + given < len(text)
            and _is_han(text[j + given])
            and text[j + given] not in GIVEN_STOP
            and not _TITLE_AFTER_RE.match(text, j + given)
        ):
            given += 1
        for count in range(given, minimum - 1, -1):
            span = (i, j + count)
            if _acceptable(text, span):
                found.append(span)
    return sorted(set(found), key=lambda s: s[0] - s[1])


def _acceptable(text: str, span: Span) -> bool:
    word = text[span[0] : span[1]].replace("\n", "")
    return word not in COMMON and not any(city in word or word in city for city in CITIES)


def _right_ok(text: str, end: int, *, verb: bool) -> bool:
    """What follows the name: a verb or a particle, a title, or (unless `verb`) anything but Han."""
    if end >= len(text):
        return not verb
    char = text[end]
    if char in RIGHT_OK or _TITLE_AFTER_RE.match(text, end):
        return True
    return not verb and not _is_han(char)


def _left_ok(text: str, start: int) -> bool:
    if start == 0 or not _is_han(text[start - 1]):
        return True
    return _LEFT_RE.search(text, max(0, start - 8), start) is not None


def _after_left_word(text: str, start: int) -> bool:
    return start > 0 and _LEFT_RE.search(text, max(0, start - 8), start) is not None


def _best(text: str, start: int, *, verb: bool, minimum: int = 1) -> Span | None:
    for span in _candidates(text, start, minimum=minimum):
        if _right_ok(text, span[1], verb=verb):
            return span
    if minimum == 1 and not verb:
        # a surname alone, written right before its title ("郝女士")
        for span in _candidates(text, start, minimum=0):
            if _TITLE_AFTER_RE.match(text, span[1]) and _right_ok(text, span[1], verb=False):
                return span
    return None


def _in_organisation_words(word: str) -> bool:
    return any(item in word for item in ORGANISATION)


def _line_spans(text: str) -> list[Span]:
    """A name alone on its line, or alone in a table cell or list item."""
    spans: list[Span] = []
    offset = 0
    for line in text.split("\n"):
        cells: list[Span] = []
        previous = 0
        for cell in re.finditer(r"[|\t]", line):
            cells.append((previous, cell.start()))
            previous = cell.end()
        cells.append((previous, len(line)))
        for a, b in cells:
            raw = line[a:b]
            lead = len(raw) - len(raw.lstrip(_LINE_MARKS))
            content = raw.strip(_LINE_MARKS)
            if not 2 <= len(content) <= 5 or not all(_is_han(c) for c in content):
                continue
            if _in_organisation_words(content) or content[-1] in SUFFIX_CHARS:
                continue
            start = offset + a + lead
            for span in _candidates(text, start):
                if span[1] == start + len(content):
                    spans.append(span)
                    break
        offset += len(line) + 1
    return spans


def _dot_spans(text: str) -> list[Span]:
    """ "阿依古丽·买买提": two Han words joined by a middle dot are a minority or foreign name."""
    spans: list[Span] = []
    for match in re.finditer(f"[{_DOT}]", text):
        dot = match.start()
        left = dot
        while left > 0 and _is_han(text[left - 1]) and dot - left < 5:
            left -= 1
        stripped = True
        while stripped:
            stripped = False
            for word in (*LABELS, *LEFT_WORDS, *TITLES_BEFORE):
                if text.startswith(word, left) and left + len(word) <= dot - 2:
                    left += len(word)
                    stripped = True
                    break
        start = dot + 1
        if start < len(text) and text[start] == "\n":
            start += 1
        right = start
        while right < len(text) and _is_han(text[right]) and right - start < 5:
            right += 1
        for index in range(start + 2, right):
            if text[index] in DOT_STOP or _TITLE_AFTER_RE.match(text, index):
                right = index
                break
        if dot - left >= 2 and right - start >= 2:
            word = text[left:right]
            if not _in_organisation_words(word) and not any(city in word for city in CITIES):
                spans.append((left, right))
    return spans


def han_spans(text: str) -> list[Span]:
    """Han names found by rule (see the module text)."""
    if not _HAN.search(text):
        return []
    spans = [*_line_spans(text), *_dot_spans(text)]
    for match in _LABEL_RE.finditer(text):
        position = match.end()
        title = _TITLE_BEFORE_RE.match(text, position)
        if title:
            position = title.end()
        found = _best(text, position, verb=False)
        if found:
            spans.append(found)
    for match in _TITLE_BEFORE_RE.finditer(text):
        found = _best(text, match.end(), verb=False)
        if found:
            spans.append(found)
    for match in _TITLE_AFTER_RE.finditer(text):
        end = match.start()
        if not _right_ok(text, match.end(), verb=False):
            continue
        for length in (4, 3, 2, 1):
            start = end - length
            if start < 0 or not all(_is_han(c) for c in text[start:end]):
                continue
            if not _left_ok(text, start):
                continue
            for lead in _surname_lengths(text, start):
                given = text[start + lead : end]
                if len(given) <= 2 and not any(char in GIVEN_STOP for char in given):
                    span = (start, end)
                    if _acceptable(text, span) or length == 1:
                        spans.append(span)
                        break
            else:
                continue
            break
    for index in range(len(text)):
        if _is_han(text[index]) and _surname_lengths(text, index):
            trigger = _after_left_word(text, index)
            if not trigger and index and _is_han(text[index - 1]):
                continue
            named = _best(text, index, verb=not trigger)
            if named and (trigger or _is_sentence_start(text, index)):
                spans.append(named)
    return spans


def _is_sentence_start(text: str, index: int) -> bool:
    return index == 0 or not _is_han(text[index - 1])


def trim_titles(text: str, span: Span) -> list[Span]:
    """The pieces of a model span without the title words in it. In Han text a title inside the
    span is cut out ("陶老师 (Sales)" gives "陶" and "(Sales)"), and a title at its start or end is
    cut off ("张经理" gives "张"). In romanised text a role word at its start is cut off ("Manager
    Peng" gives "Peng"). Nothing left: an empty list."""
    start, end = span
    if not _HAN.search(text, start, end):
        return [_trim_roles(text, span)]
    pieces = [span]
    for match in re.finditer("|".join(TITLES_AFTER_LONG), text[start:end]):
        pieces = [
            part
            for piece in pieces
            for part in _cut(piece, start + match.start(), start + match.end())
        ]
    result: list[Span] = []
    for piece in pieces:
        trimmed = _trim_ends(text, piece)
        if trimmed:
            result.append(trimmed)
    return result


def _cut(piece: Span, start: int, end: int) -> list[Span]:
    if end <= piece[0] or start >= piece[1]:
        return [piece]
    return [part for part in ((piece[0], start), (end, piece[1])) if part[0] < part[1]]


def _trim_roles(text: str, span: Span) -> Span:
    start, end = span
    while True:
        word = re.compile(r"(?:General[ ])?[A-Za-z]+[ \t]+").match(text, start, end)
        if word is None or word.group().split()[-1].lower() not in _ROLE_WORDS or word.end() >= end:
            return start, end
        start = word.end()


def _trim_ends(text: str, span: Span) -> Span | None:
    start, end = span
    changed = True
    while changed and start < end:
        changed = False
        for word in TITLES_AFTER:
            if end - start > len(word) and text.endswith(word, start, end):
                end -= len(word)
                changed = True
        for word in TITLES_BEFORE:
            if end - start > len(word) and text.startswith(word, start, end):
                start += len(word)
                changed = True
    return (start, end) if start < end else None


def in_organisation(text: str, span: Span) -> bool:
    """A model span inside a Han company, product or place name: an organisation word follows it
    in the same run of Han characters, or it is a city."""
    start, end = span
    if not _HAN.search(text, start, end):
        return False
    stop = end
    while stop < len(text) and _is_han(text[stop]) and text[stop] not in _RUN_STOP:
        stop += 1
    tail = text[start:stop]
    if _in_organisation_words(tail):
        return True
    if end < len(text) and text[end] in SUFFIX_CHARS:
        return True
    if end - start >= 3 and text[end - 1] in SUFFIX_CHARS:
        return True
    return any(tail.startswith(city) for city in CITIES)


# ---- romanised -------------------------------------------------------------------------------
_INITIALS: Final = "zh|ch|sh|kw|gw|ng|ts|tz|hs|sz|b|p|m|f|d|t|n|l|g|k|h|j|q|x|r|z|c|s|y|w"
_SYLLABLE: Final = rf"(?:(?:{_INITIALS})?[aeiouüv]+(?:ng|n|m|h|k|t|p|r)?|tsz|sz|tz)"
_SYLLABIC: Final = re.compile(rf"(?:{_SYLLABLE}){{1,4}}", re.IGNORECASE)
_WORD: Final = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)*")
_ROLE_WORDS: Final = frozenset(
    """manager director engineer supervisor president chairman chairwoman professor general mister
    madam miss sales purchasing procurement account buyer owner founder officer head chief senior
    junior assistant secretary representative""".split()
)
_PLACE_ENDINGS: Final = frozenset("zhen cun gang hu qiao zhuang gou dao".split())
# Words after a name that make it a company, a product or a place.
NOUNS: Final = frozenset(
    """plastic plastics packaging package packing mould mold molding tooling closure closures
    cap caps seal seals liner liners film films tray trays bottle bottles lid lids pack
    packs tube tubes bag bags box boxes container containers glass metal metals machinery
    equipment engineering materials material chemical chemicals printing paper rubber
    textile textiles garment food foods foodstuff steel logistics shipping freight trading
    trade industrial industry industries technology technologies electronics electronic
    manufacturing manufacturer precision products group holding holdings development
    investment import export co company corporation limited ltd inc llc plc pte road street
    avenue park zone district town village area city province new high-tech development""".split()
)
# Place words that make Chinese-sounding words an address or a district, not a person.
PLACE_WORDS: Final = frozenset("road street avenue district zone town village".split())
# The industry words of NOUNS: a model span that holds one, next to Chinese-sounding words, is a
# product or a company; the place words (road, park) are left out, "Park" is a surname.
INDUSTRY: Final = frozenset(
    word
    for word in NOUNS
    if word
    not in "road street avenue park zone district town village area city province new co company "
    "corporation limited ltd inc llc plc pte group holding holdings development high-tech".split()
)
_CITIES_LATIN: Final = frozenset(
    """suzhou wuxi ningbo dongguan foshan chengdu wuhan qingdao tianjin xiamen kunshan changzhou
    shanghai beijing nanjing guangzhou shenzhen hangzhou hong kong taiwan macau macao taipei
    chongqing shenyang dalian jiangsu zhejiang guangdong fujian shandong henan hubei hunan sichuan
    anhui hebei yunnan guizhou""".split()
)
_ROLES_LATIN: Final = re.compile(
    r"(?<![\w-])(?:General Manager|Manager|Director|Engineer|Supervisor|President|Chairman|"
    r"Mr|Mrs|Ms|Miss|Dr|Prof|Professor)\.?[ \t]+([A-Z][a-z]+|[A-Z]{2,})(?![\w-])"
)
_LINE_LATIN_MARKS: Final = " \t-•*|"
_LABEL_LATIN: Final = re.compile(
    r"(?:contact(?:\s+person)?|name|signed\s+by|attn|regards|sincerely)\s*[:,]\s*", re.IGNORECASE
)


def _syllabic(token: str) -> bool:
    if token.lower().replace("-", "") in _pinyin_surnames():
        return True
    return all(_SYLLABIC.fullmatch(part) for part in token.split("-"))


def _capitalised(token: str) -> bool:
    head = token.split("-")[0]
    if len(head) >= 2 and head.isupper() and token.replace("-", "").isalpha():
        return True
    return head[:1].isupper() and head[1:].islower() or (len(head) == 1 and head.isupper())


def _is_surname(token: str) -> bool:
    return token.lower().replace("-", "") in _pinyin_surnames()


def _blocks(line: str, tokens: list[re.Match[str]], *, lower: bool) -> list[list[re.Match[str]]]:
    """Runs of words that follow each other after blanks only and all read as name words."""
    blocks: list[list[re.Match[str]]] = []
    current: list[re.Match[str]] = []
    for token in tokens:
        word = token.group()
        name_word = (
            word.lower() not in _ROLE_WORDS
            and _syllabic(word)
            and (word.islower() if lower else _capitalised(word))
        )
        joined = bool(current) and re.fullmatch(r"[ \t]+", line[current[-1].end() : token.start()])
        if name_word and (not current or joined):
            current.append(token)
            continue
        if current:
            blocks.append(current)
        current = [token] if name_word else []
    if current:
        blocks.append(current)
    return blocks


def _name_block(block: list[re.Match[str]], line: str) -> Span | None:
    """The span of `block` when it reads as a romanised Chinese name, else None."""
    if not 2 <= len(block) <= 4:
        return None
    words = [t.group() for t in block]
    keys = [w.lower() for w in words]
    if any(k in _CITIES_LATIN or k in NOUNS for k in keys) or "hong kong" in " ".join(keys):
        return None
    if not (_is_surname(words[0]) or _is_surname(words[-1])):
        return None
    if len(block) >= 3 and keys[-1] in _PLACE_ENDINGS:
        return None
    following = re.compile(r"[ \t]+([A-Za-z-]+)").match(line, block[-1].end())
    if following and following.group(1).lower() in NOUNS | _CITIES_LATIN:
        return None
    return block[0].start(), block[-1].end()


def latin_spans(text: str) -> list[Span]:
    """Romanised Chinese names found by rule (see the module text)."""
    if not any(char.isalpha() and char.isascii() for char in text):
        return []
    spans: list[Span] = []
    offset = 0
    for line in text.split("\n"):
        tokens = list(_WORD.finditer(line))
        for block in _blocks(line, tokens, lower=False):
            found = _name_block(block, line)
            if found:
                spans.append((offset + found[0], offset + found[1]))
        # a lower-case name: alone on its line, or right after a label
        content = line.strip(_LINE_LATIN_MARKS)
        if content and content == content.lower():
            start = line.index(content)
            label = _LABEL_LATIN.match(content)
            body_start = start + (label.end() if label else 0)
            body = line[body_start:].rstrip(_LINE_LATIN_MARKS)
            if re.fullmatch(r"[a-z]+(?:-[a-z]+)*(?:[ \t]+[a-z]+(?:-[a-z]+)*)*", body):
                inside = [t for t in tokens if t.start() >= body_start]
                for block in _blocks(line, inside, lower=True):
                    found = _name_block(block, line)
                    if found and len(block) == len(inside):
                        spans.append((offset + found[0], offset + found[1]))
        for match in _ROLES_LATIN.finditer(line):
            token = match.group(1)
            if _is_surname(token) and not re.match(r"[ \t]+[A-Z][a-z]", line[match.end() :]):
                spans.append((offset + match.start(1), offset + match.end(1)))
        offset += len(line) + 1
    return spans


def is_organisation(text: str, span: Span) -> bool:
    """A model span that is a Chinese company, product or place, not a person: in Han text an
    organisation word follows it (`in_organisation`); in romanised text it is Chinese-sounding
    words and a company, product or place noun ("Li Shan Seal", "Jianglei Cap")."""
    if _HAN.search(text, span[0], span[1]):
        return in_organisation(text, span)
    inside = re.sub(r"['\u2019]s\b", "", text[span[0] : span[1]])
    words = _WORD.findall(inside)
    markers = INDUSTRY | PLACE_WORDS
    nouns = sum(1 for word in words if word.lower() in markers)
    words = [word for word in words if word.lower() not in markers]
    following = re.compile(r"[ \t]+([A-Z][A-Za-z-]+)").match(text, span[1])
    if following is not None and following.group(1).lower() in markers:
        nouns += 1
    return bool(nouns and words and all(_syllabic(word) for word in words))
