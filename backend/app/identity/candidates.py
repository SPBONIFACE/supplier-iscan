"""From a registry candidate to the contract's IdentityCandidate, and the natural-person flag."""

import re
import unicodedata
from typing import Any

from app.countries import normalise_code
from app.registries import RegistryCandidate
from app.registries.text import match_key

# Legal forms of a sole trader or another natural-person business (spec F1, F8 excluded uses).
# Matched on the legal-form label published by the registry; a form not listed is not flagged.
# The label is normalised first: lower case, no accents, dots removed, other signs as spaces.
_LONG_FORMS = re.compile(
    r"sole\s+(trader|proprietor)|self\s+employed|selbst(st)?(ae|a)ndig|individual\s+(entrepreneur|business)"
    r"|individual\s+proprietor|natural\s+person|entrepreneur\s+individuel|entreprise\s+individuelle"
    r"|auto\s?entrepreneur|micro\s?entrepreneur|micro\s?entreprise|travailleur\s+independant"
    r"|einzelunternehmer|einzelunternehmen|einzelfirma|einzelkaufmann|eingetragener\s+kaufmann|freiberuf"
    r"|ditta\s+individuale|impresa\s+individuale|libero\s+professionista|eenmanszaak"
    r"|empresario\s+individual|persona\s+fisica|autonomo|enskild\s+firma|enkeltmandsvirksomhed"
    r"|doing\s+business\s+as"
)
# Short abbreviations: only as a whole token, and never when the label also carries a company form.
_SHORT_FORMS = re.compile(r"(?<![a-z0-9])(eirl|ei|e\s?k|d\s?b\s?a)(?![a-z0-9])")
_COMPANY_FORMS = re.compile(
    r"(?<![a-z0-9])(sas|sasu|sarl|eurl|sa|gmbh|ug|ltd|limited|llc|llp|inc|corp|sl|slu|srl|spa|ag|kg|ohg"
    r"|bv|nv|plc|sci|oy|ab|as|aps)(?![a-z0-9])"
)


def _normalise(label: str) -> str:
    text = unicodedata.normalize("NFKD", label.lower())
    text = "".join(c for c in text if not unicodedata.combining(c)).replace("\u00df", "ss")
    text = text.replace(".", "")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def candidate_id(candidate: RegistryCandidate) -> str:
    return f"lei:{candidate.lei}" if candidate.lei else f"wd:{candidate.wikidata_id}"


def is_natural_person(legal_form: str | None) -> bool:
    if not legal_form:
        return False
    text = _normalise(legal_form)
    if _LONG_FORMS.search(text):
        return True
    return bool(_SHORT_FORMS.search(text)) and not _COMPANY_FORMS.search(text)


# Key of `IdentitySession.hints` where the country the buyer stated in the chat is kept (never in a
# response: the contract's hints are website, country, sector).
STATED_COUNTRY = "stated_country"


def entry_from_registry(candidate: RegistryCandidate) -> dict[str, Any]:
    """The stored form: the public candidate, plus what only the server needs."""
    identifiers = []
    if candidate.lei:
        identifiers.append({"scheme": "LEI", "value": candidate.lei})
    if candidate.wikidata_id:
        identifiers.append({"scheme": "Wikidata", "value": candidate.wikidata_id})
    public = {
        "id": candidate_id(candidate),
        "legal_name": candidate.legal_name or candidate.name,
        "legal_form": candidate.legal_form,
        "website": candidate.website,
        "country": normalise_code(candidate.country),  # ISO alpha-2 code; the UI shows the name
        "sector": ", ".join(candidate.industries[:3]) or None,
        "description": candidate.description,
        "found_in": list(candidate.registries),
        "identifiers": identifiers,
    }
    natural_person = is_natural_person(candidate.legal_form)
    return {
        "candidate": public,
        "natural_person": natural_person,
        "wikidata_id": candidate.wikidata_id,
        "lei": candidate.lei,
        "lei_status": candidate.lei_status,
        "country_code": normalise_code(
            candidate.country
        ),  # same as the public one; kept for #135 rows
        # Server-only, never in `candidate` (the public part): a sole trader's registry address is
        # personal data, kept for redaction. A company's address is not kept.
        "registered_address": candidate.registered_address if natural_person else None,
    }


# Legal-form words dropped from the end of a legal name before two names are compared (#142).
_FORM_WORDS = frozenset(
    "sa sas sasu sarl eurl sca snc gmbh ag se kg ohg ug mbh co ltd limited llc llp lp inc corp "
    "corporation incorporated company plc bv nv spa srl sl slu ab as asa oy oyj aps sp zoo "
    "pty pte".split()
)


def comparable_name(name: str) -> str:
    """A legal name without case, accents, punctuation and trailing legal-form words."""
    words = match_key(name.replace(".", "")).split()
    while len(words) > 1 and words[-1] in _FORM_WORDS:
        words.pop()
    return " ".join(words)


def unique_active_lei(entry: dict[str, Any], entries: list[dict[str, Any]]) -> str | None:
    """The LEI an LEI-less candidate gets at confirmation (#142): the LEI of the one active GLEIF
    candidate of the session with the same comparable legal name and the same country; None
    when there is none, or more than one."""
    country = entry["candidate"].get("country")
    name = comparable_name(entry["candidate"]["legal_name"])
    if not country or not name:
        return None
    leis = {
        other["lei"]
        for other in entries
        if other is not entry
        and other.get("lei")
        and str(other.get("lei_status") or "").upper() == "ACTIVE"
        and "gleif" in other["candidate"].get("found_in", [])
        and other["candidate"].get("country") == country
        and comparable_name(other["candidate"]["legal_name"]) == name
    }
    return leis.pop() if len(leis) == 1 else None


def entry_from_website(name: str, final_url: str, domain: str) -> dict[str, Any]:
    public = {
        "id": f"web:{domain}",
        "legal_name": name,
        "legal_form": None,
        "website": final_url,
        "country": None,
        "sector": None,
        "description": None,
        "found_in": ["website"],
        "identifiers": [{"scheme": "domain", "value": domain}],
    }
    return {"candidate": public, "natural_person": False, "wikidata_id": None, "lei": None}


def entry_from_web(name: str, host: str, country: str | None) -> dict[str, Any]:
    """The supplier's website found by the identity web search: a candidate the buyer confirms.
    Its country is the one the buyer gave (none found by the search is kept)."""
    entry = entry_from_website(name, f"https://{host}/", host)
    entry["candidate"] = {**entry["candidate"], "found_in": ["web"], "country": country}
    return entry
