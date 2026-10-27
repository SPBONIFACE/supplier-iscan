"""Unicode handling for supplier names (spec, Robustness cases: special characters).

Two forms are used:

- ``normalise_text``: the form that is sent to the registries and returned to the caller. NFC, with
  whitespace collapsed. Accents and non-Latin scripts are kept intact.
- ``match_key``: a comparison key only, never shown. NFKC, case-folded, accents removed from Latin
  letters only (so that "Societe Generale" matches "Société Générale"), punctuation turned into
  spaces. Marks on other scripts are kept: removing the voicing mark of a Japanese kana would turn
  it into a different character.
"""

import unicodedata

# Upper bound of the Latin blocks whose combining marks are accents (Basic Latin to IPA
# Extensions, then Latin Extended Additional).
_LATIN_RANGES = ((0x0000, 0x024F), (0x1E00, 0x1EFF))


def normalise_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _is_latin(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _LATIN_RANGES)


def match_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    kept: list[str] = []
    base_is_latin = False
    for char in decomposed:
        if unicodedata.combining(char):
            if base_is_latin:
                continue
        else:
            base_is_latin = _is_latin(char)
        kept.append(char)
    folded = unicodedata.normalize("NFKC", "".join(kept)).casefold()
    cleaned = "".join(char if char.isalnum() else " " for char in folded)
    return " ".join(cleaned.split())


def search_languages(name: str) -> tuple[str, ...]:
    """Wikidata label languages to search in, from the scripts used in the name.

    English is always searched. A Latin-script name is also searched in French and German (the UI
    languages and the main European markets of the spec); a non-Latin name in the languages of its
    script. The hints never change this list, so they cannot add or remove candidates.
    """
    has_kana = has_han = has_hangul = has_cyrillic = has_greek = has_arabic = has_hebrew = False
    for char in name:
        code = ord(char)
        if 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF:
            has_kana = True
        elif 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
            has_han = True
        elif 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF:
            has_hangul = True
        elif 0x0400 <= code <= 0x04FF:
            has_cyrillic = True
        elif 0x0370 <= code <= 0x03FF:
            has_greek = True
        elif 0x0600 <= code <= 0x06FF:
            has_arabic = True
        elif 0x0590 <= code <= 0x05FF:
            has_hebrew = True
    script_languages: list[str] = []
    if has_kana:
        script_languages.append("ja")
    if has_han and not has_kana:
        script_languages.extend(["zh", "ja"])
    if has_hangul:
        script_languages.append("ko")
    if has_cyrillic:
        script_languages.append("ru")
    if has_greek:
        script_languages.append("el")
    if has_arabic:
        script_languages.append("ar")
    if has_hebrew:
        script_languages.append("he")
    if script_languages:
        return (*script_languages, "en")
    return ("en", "fr", "de")
