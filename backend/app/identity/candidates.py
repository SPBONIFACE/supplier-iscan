"""From a registry candidate to the contract's IdentityCandidate, and the natural-person flag."""

import re
from typing import Any

from app.registries import RegistryCandidate

# Legal forms of a sole trader or another natural-person business (spec F1, F8 excluded uses).
# Matched on the legal-form label published by the registry; a form not listed is not flagged.
_NATURAL_PERSON_FORMS = re.compile(
    r"sole\s+(trader|proprietor)|self[- ]employed|individual\s+(entrepreneur|business)"
    r"|natural\s+person|entrepreneur\s+individuel|auto[- ]?entrepreneur|micro[- ]?entrepreneur"
    r"|\bEIRL?\b|einzelunternehmen|einzelkaufmann|eingetragener\s+kaufmann|freiberuf"
    r"|ditta\s+individuale|impresa\s+individuale|eenmanszaak|empresario\s+individual"
    r"|persona\s+f[ií]sica|aut[oó]nomo|enskild\s+firma|enkeltmandsvirksomhed",
    re.IGNORECASE,
)


def candidate_id(candidate: RegistryCandidate) -> str:
    return f"lei:{candidate.lei}" if candidate.lei else f"wd:{candidate.wikidata_id}"


def is_natural_person(legal_form: str | None) -> bool:
    return bool(legal_form and _NATURAL_PERSON_FORMS.search(legal_form))


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
    return {
        "candidate": public,
        "natural_person": is_natural_person(candidate.legal_form),
        "wikidata_id": candidate.wikidata_id,
        "lei": candidate.lei,
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
