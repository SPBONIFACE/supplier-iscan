"""Merge Wikidata and GLEIF candidates, then rank them.

Merging: a Wikidata item whose LEI (P1278) equals a GLEIF record's LEI is one company, shown once.

Ranking: a score from the closeness of the name, adjusted by the hints. Hints only reorder: the
function returns exactly the candidates it was given (spec F1: a hint never removes a candidate).
"""

from collections.abc import Sequence
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from app.registries.models import RegistryCandidate, RegistrySearchQuery
from app.registries.text import match_key

BOTH_REGISTRIES_BONUS = 0.1
INACTIVE_LEI_PENALTY = 0.2
COUNTRY_MATCH = 0.5
COUNTRY_MISMATCH = -0.5
WEBSITE_MATCH = 0.6
WEBSITE_MISMATCH = -0.3
SECTOR_MATCH = 0.3


def merge_candidates(
    wikidata: Sequence[RegistryCandidate], gleif: Sequence[RegistryCandidate]
) -> list[RegistryCandidate]:
    gleif_by_lei = {c.lei: c for c in gleif if c.lei}
    merged_leis: set[str] = set()
    merged: list[RegistryCandidate] = []
    for item in wikidata:
        record = gleif_by_lei.get(item.lei) if item.lei else None
        if record is None or record.lei in merged_leis:
            merged.append(item)
            continue
        merged_leis.add(record.lei or "")
        country = record.country or item.country
        merged.append(
            RegistryCandidate(
                name=item.name,
                legal_name=record.legal_name,
                description=item.description,
                website=item.website,
                country=country,
                country_name=item.country_name if item.country in (None, country) else None,
                industries=item.industries,
                legal_form=item.legal_form or record.legal_form,
                legal_form_code=record.legal_form_code,
                registered_address=record.registered_address,
                wikidata_id=item.wikidata_id,
                lei=record.lei,
                lei_status=record.lei_status,
                registries=("wikidata", "gleif"),
            )
        )
    merged.extend(c for c in gleif if c.lei not in merged_leis)
    return merged


def _name_score(query_key: str, candidate: RegistryCandidate) -> float:
    best = 0.0
    for name in (candidate.name, candidate.legal_name):
        if not name:
            continue
        key = match_key(name)
        if key == query_key:
            score = 1.0
        elif key.startswith(query_key) or query_key in key:
            score = 0.8
        else:
            score = 0.7 * SequenceMatcher(None, query_key, key).ratio()
        best = max(best, score)
    return best


def _host(value: str) -> str | None:
    text = value.strip()
    if "://" not in text:
        text = "http://" + text
    try:
        host = urlsplit(text).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.casefold().rstrip(".")
    return host.removeprefix("www.")


def _same_site(left: str, right: str) -> bool:
    return left == right or left.endswith("." + right) or right.endswith("." + left)


def _country_codes_by_name(candidates: Sequence[RegistryCandidate]) -> dict[str, str]:
    """Country names seen in the candidates (Wikidata labels), mapped to their ISO codes."""
    return {
        match_key(c.country_name): c.country for c in candidates if c.country_name and c.country
    }


def _country_adjustment(
    hint: str, candidate: RegistryCandidate, codes_by_name: dict[str, str]
) -> float:
    hint_key = match_key(hint)
    hint_code = hint.upper() if len(hint) == 2 and hint.isalpha() else codes_by_name.get(hint_key)
    if hint_code and candidate.country:
        return COUNTRY_MATCH if candidate.country == hint_code else COUNTRY_MISMATCH
    if candidate.country_name:
        return COUNTRY_MATCH if match_key(candidate.country_name) == hint_key else COUNTRY_MISMATCH
    return 0.0


def _website_adjustment(hint: str, candidate: RegistryCandidate) -> float:
    hint_host = _host(hint)
    candidate_host = _host(candidate.website) if candidate.website else None
    if not hint_host or not candidate_host:
        return 0.0
    return WEBSITE_MATCH if _same_site(hint_host, candidate_host) else WEBSITE_MISMATCH


def _sector_adjustment(hint: str, candidate: RegistryCandidate) -> float:
    hint_key = match_key(hint)
    if not hint_key:
        return 0.0
    texts = [*candidate.industries, candidate.description or ""]
    for text in texts:
        key = match_key(text)
        if key and (hint_key in key or key in hint_key):
            return SECTOR_MATCH
    return 0.0


def score_candidate(
    query: RegistrySearchQuery,
    candidate: RegistryCandidate,
    codes_by_name: dict[str, str] | None = None,
) -> float:
    score = _name_score(match_key(query.name), candidate)
    if len(candidate.registries) > 1:
        score += BOTH_REGISTRIES_BONUS
    if candidate.lei_status and candidate.lei_status.upper() != "ACTIVE":
        score -= INACTIVE_LEI_PENALTY
    if query.country_hint:
        score += _country_adjustment(query.country_hint, candidate, codes_by_name or {})
    if query.website_hint:
        score += _website_adjustment(query.website_hint, candidate)
    if query.sector_hint:
        score += _sector_adjustment(query.sector_hint, candidate)
    return score


def rank_candidates(
    query: RegistrySearchQuery, candidates: Sequence[RegistryCandidate]
) -> list[RegistryCandidate]:
    codes_by_name = _country_codes_by_name(candidates)
    scored = [
        (score_candidate(query, candidate, codes_by_name), index, candidate)
        for index, candidate in enumerate(candidates)
    ]
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return [candidate for _, _, candidate in scored]
