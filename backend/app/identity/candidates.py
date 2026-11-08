"""From a registry candidate to the contract's IdentityCandidate, and the natural-person flag."""

import re
import unicodedata
from typing import Any

from app.registries import RegistryCandidate

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
        "country": candidate.country_name or candidate.country,
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
        # Server-only, never in `candidate` (the public part): a sole trader's registry address is
        # personal data, kept for redaction. A company's address is not kept.
        "registered_address": candidate.registered_address if natural_person else None,
    }


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
