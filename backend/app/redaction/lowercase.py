"""Names written entirely in lower case, found only from a clue next to them (#19, owner decision).

No name list and no model: a lower-case word is taken for part of a name only
- right after an honorific ("m. dupont", "dr schmidt"),
- right after a label, a "signed by" or a closing ("contact: jean dupont", "ansprechpartner: hans
  meier"), two words at least,
- or just before a job title ("jean dupont, directeur achats", "anna schmidt, head of purchasing").
Each word must pass a closed-class filter: not an article, preposition, pronoun, conjunction,
role, company or heading word. Lower-case names with no clue next to them are not detected (a
stated limit).
"""

import re
from typing import Final

from app.redaction.names import (
    _LABEL_LINE,
    FUNCTION_WORDS,
    PARTICLES,
    ROLES,
    ROLES_EXTRA,
    WORD,
    Span,
    _body,
    _kind,
    fold,
    not_a_name,
)

_HONORIFIC: Final = re.compile(
    r"(?<![\w.])(?<!\d[ \t])(?:m\.|mme|mlle|mr|mrs|dr|prof\.|herr|frau|sra?|srta|sig\.?|dott\.?|"
    r"monsieur|madame|mademoiselle|señor|señora|signor|signora)\.?[ \t]+(?=[^\W\d_])"
)
_ELIDED: Final = re.compile(r"[dl]['’]")
_WORD_SHAPE: Final = re.compile(r"[^\W\d_]+(?:[-'’‐][^\W\d_]+)*")
_BLANKS: Final = re.compile(r"[ \t]+")
_SEPARATOR: Final = re.compile(r"[ \t]*[,;|–—-][ \t]*")
# The words of a sign-off ("kind regards", "viele grüße"): never a name.
_SIGN_OFF: Final = frozenset(
    fold(word)
    for word in """kind best warm warmest regards wishes sincerely faithfully greetings thanks
    thank cheers cordially respectfully cordialement salutations distinguées amicalement
    sincères respectueuses meilleures grüße gruesse grüßen grussen freundlichen freundliche
    besten viele herzliche saludos atentamente cordial cordiales abrazo saluti cordiali distinti
    cordialmente cari""".split()
)
_NOT_ROLE_HEADS: Final = frozenset(
    fold(w) for w in "eine miss madam herr frau dott team equipe".split()
)


def _is_particle(token: str) -> bool:
    body = _body(token)
    return fold(body) in PARTICLES and _kind(body) == "low"


def _is_weak_particle(token: str) -> bool:
    """ "la" and "le" are ordinary articles: part of a name only after another particle."""
    return fold(_body(token)) in ("la", "le")


def _low_name(token: str) -> bool:
    """A lower-case word that can be part of a name."""
    body = _body(token)
    key = fold(body)
    if len(key) < 2 or _kind(body) != "low" or _ELIDED.match(key):
        return False
    if _WORD_SHAPE.fullmatch(body) is None:
        return False
    return key not in FUNCTION_WORDS and key not in _SIGN_OFF and not not_a_name(key, common=True)


def _run(text: str, pos: int, *, minimum: int, honorific: bool = False) -> Span | None:
    """Up to two lower-case name words (and particles) at `pos`, on one line. After an honorific
    "le" and "la" start a name ("mme le gallic")."""
    first: int | None = None
    end, count, position = pos, 0, pos
    previous_particle = honorific
    while count < 2:
        match = WORD.match(text, position)
        if match is None or (match.end() < len(text) and text[match.end()].isdigit()):
            break
        token = match.group()
        if _is_particle(token) and (previous_particle or not _is_weak_particle(token)):
            first = match.start() if first is None else first
            previous_particle = True
            gap = _BLANKS.match(text, match.end())
            if gap is None:
                break
            position = gap.end()
            continue
        previous_particle = False
        if _low_name(token):
            first = match.start() if first is None else first
            end = match.end() - (len(token) - len(_body(token)))
            count += 1
            if _body(token) != token:
                break
        else:
            break
        gap = _BLANKS.match(text, match.end())
        if gap is None:
            break
        position = gap.end()
    if first is None or count < minimum:
        return None
    return first, end


def _back(text: str, stop: int) -> Span | None:
    """The two lower-case name words (three at the start of a clause) that end at `stop`."""
    line_start = text.rfind("\n", 0, stop) + 1
    picked: list[re.Match[str]] = []
    count = 0
    expected_end = stop
    for match in reversed(list(WORD.finditer(text, line_start, stop))):
        if text[match.end() : expected_end].strip(" \t") or match.end() > expected_end:
            break
        token = match.group()
        if _is_particle(token):
            picked.append(match)
        elif token == _body(token) and _low_name(token):
            picked.append(match)
            count += 1
        else:
            break
        expected_end = match.start()
        if count == 3:
            break
    for index, match in enumerate(picked):
        if _is_weak_particle(match.group()) and (
            index + 1 >= len(picked) or not _is_particle(picked[index + 1].group())
        ):
            picked = picked[:index]  # "la" and "le" belong to a name only after "de", "du" ...
            break
    count = sum(not _is_particle(match.group()) for match in picked)
    while picked and _is_particle(picked[-1].group()):
        picked.pop()  # a particle needs a name word after it, not before the run
    if count < 2 or not picked:
        return None
    if count == 3:
        lead = text[line_start : picked[-1].start()].rstrip(" \t")
        if lead and lead[-1].isalpha():
            # mid-sentence: the third word is more likely prose ("ask anna schmidt, head of ...")
            picked.pop()
    first = picked[-1]
    last = picked[0]
    return first.start(), last.end() - (len(last.group()) - len(_body(last.group())))


def spans(text: str) -> tuple[list[Span], list[Span]]:
    """Lower-case names with a clue: honorific, label or closing before, job title after.

    Returns (strong, to_confirm): after an honorific or before a job title the clue is enough;
    after a label the words must still look like a name, which the caller checks with the NER
    on a capitalised copy ("contact: sales desk" is not a name, "contact: jean dupont" is).
    """
    found: list[Span] = []
    to_confirm: list[Span] = []
    for match in _HONORIFIC.finditer(text):
        run = _run(text, match.end(), minimum=1, honorific=True)
        if run:
            found.append(run)
    for match in _LABEL_LINE.finditer(text):
        run = _run(text, match.end(), minimum=2)
        if run:
            to_confirm.append(run)
    for match in _SEPARATOR.finditer(text):
        role = WORD.match(text, match.end())
        if role is None:
            continue
        key = fold(_body(role.group()))
        if len(key) > 3 and key in (ROLES | ROLES_EXTRA) and key not in _NOT_ROLE_HEADS:
            back = _back(text, match.start())
            if back:
                found.append(back)
    return found, to_confirm


def capitalised_copy(text: str, span: Span) -> str:
    """The text with the first letter of each word of the span in upper case (same offsets)."""
    chars = list(text)
    for match in WORD.finditer(text, span[0], span[1]):
        upper = chars[match.start()].upper()
        if len(upper) == 1:
            chars[match.start()] = upper
    return "".join(chars)
