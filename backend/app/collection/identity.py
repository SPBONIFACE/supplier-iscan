"""Does the confirmed legal name appear on the supplier's own website? (spec F1, "identity to
verify"). Compared in lower case, without accents or punctuation, and without legal-form suffixes.
"""

import re
import unicodedata
from collections.abc import Iterable

LEGAL_FORMS = frozenset(
    {
        "sa", "sas", "sasu", "sarl", "eurl", "snc", "sca", "scs", "se", "gmbh", "ag", "kg", "ug",
        "ohg", "mbh", "co", "ltd", "limited", "llc", "lp", "llp", "inc", "incorporated", "corp",
        "corporation", "plc", "company", "spa", "srl", "bv", "nv", "ab", "oy", "as", "aps", "sl",
        "sro", "ek", "ev", "cie", "et",
    }
)  # fmt: skip
_NON_WORD = re.compile(r"[^\w]+")


def fold(text: str) -> str:
    # "S.A.S." and "S.A.S" are "SAS"; apostrophes join (l'été, O'Brien) on both sides alike.
    text = text.replace("ß", "ss").casefold().replace(".", "").replace("'", "").replace("’", "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(_NON_WORD.sub(" ", text).split())


def core_name(legal_name: str) -> str:
    """The name without its legal-form suffix words (kept whole when nothing else remains)."""
    words = fold(legal_name).split()
    while len(words) > 1 and words[-1] in LEGAL_FORMS:
        words.pop()
    return " ".join(words)


def name_appears(legal_name: str, texts: Iterable[str]) -> bool:
    needle = core_name(legal_name)
    if not needle:
        return True  # nothing to look for: do not flag
    return any(f" {needle} " in f" {fold(text)} " for text in texts)
