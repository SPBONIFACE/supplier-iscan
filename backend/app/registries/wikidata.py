"""Wikidata candidates: label, description, website, country, industry, legal form, LEI.

Requests, all through the Wikidata Action API (``w/api.php``):

1. ``wbsearchentities`` once per search language (in parallel);
2. ``wbgetentities`` for the matched items (labels, descriptions, claims);
3. ``wbgetentities`` for the labels of the referenced countries, industries and legal forms;
4. ``wbgetclaims`` for the ISO 3166-1 alpha-2 code (P297) of each country (in parallel).

Labels and country codes are registry identifiers: they are cached for the configured duration.
"""

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.countries import normalise_code
from app.registries.cache import RegistryCache
from app.registries.http import PoliteHttpClient, RegistryUnavailable
from app.registries.models import RegistryCandidate, RegistryName
from app.registries.text import normalise_text, search_languages

WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
SEARCH_LIMIT = 10
MAX_ENTITIES = 20
GET_ENTITIES_BATCH = 50

P_INSTANCE_OF = "P31"
P_COUNTRY = "P17"
P_INDUSTRY = "P452"
P_WEBSITE = "P856"
P_LEI = "P1278"
P_LEGAL_FORM = "P1454"
P_ISO_ALPHA_2 = "P297"

# An item is kept as a company candidate when it has one of these properties...
_COMPANY_PROPERTIES = (
    P_LEI,
    P_INDUSTRY,
    P_LEGAL_FORM,
    "P414",  # stock exchange
    "P1128",  # employees
    "P2139",  # total revenue
    "P946",  # ISIN
)
# ... or is an instance of one of these classes.
_ORGANISATION_CLASSES = frozenset(
    {
        "Q43229",  # organization
        "Q4830453",  # business
        "Q783794",  # company
        "Q891723",  # public company
        "Q6881511",  # enterprise
        "Q167037",  # corporation
        "Q161726",  # multinational corporation
        "Q22687",  # bank
    }
)


# Transient errors of the Action API, retried after a pause.
_TRANSIENT_ERRORS = frozenset({"cirrussearch-too-busy-error", "maxlag", "ratelimited"})
TRANSIENT_RETRIES = 2
TRANSIENT_PAUSE_SECONDS = 2.0


class _TransientError(Exception):
    pass


def _check(registry_answer: Any) -> Mapping[str, Any]:
    # The Action API reports errors (e.g. "search is too busy", maxlag) with HTTP 200 and an
    # "error" object.
    if not isinstance(registry_answer, Mapping):
        raise RegistryUnavailable("wikidata", "unexpected answer")
    if "error" in registry_answer:
        error = registry_answer["error"]
        code = error.get("code") if isinstance(error, Mapping) else None
        if code in _TRANSIENT_ERRORS:
            raise _TransientError(code)
        raise RegistryUnavailable("wikidata", f"API error {code or 'unknown'}")
    return registry_answer


def _statement_values(entity: Mapping[str, Any], prop: str) -> list[Any]:
    """Values of non-deprecated statements, preferred rank first."""
    claims = entity.get("claims")
    if not isinstance(claims, Mapping):
        return []
    statements = claims.get(prop)
    if not isinstance(statements, list):
        return []
    preferred: list[Any] = []
    normal: list[Any] = []
    for statement in statements:
        if not isinstance(statement, Mapping):
            continue
        rank = statement.get("rank")
        if rank == "deprecated":
            continue
        snak = statement.get("mainsnak")
        if not isinstance(snak, Mapping) or snak.get("snaktype") != "value":
            continue
        datavalue = snak.get("datavalue")
        if not isinstance(datavalue, Mapping) or "value" not in datavalue:
            continue
        (preferred if rank == "preferred" else normal).append(datavalue["value"])
    return preferred + normal


def _item_ids(entity: Mapping[str, Any], prop: str) -> list[str]:
    ids: list[str] = []
    for value in _statement_values(entity, prop):
        if isinstance(value, Mapping) and isinstance(value.get("id"), str):
            ids.append(value["id"])
    return ids


def _strings(entity: Mapping[str, Any], prop: str) -> list[str]:
    values = _statement_values(entity, prop)
    return [normalise_text(value) for value in values if isinstance(value, str)]


def _text_in(texts: Any, languages: Sequence[str]) -> str | None:
    """The first text found in the preferred languages, else in any language."""
    if not isinstance(texts, Mapping):
        return None
    for language in languages:
        entry = texts.get(language)
        if isinstance(entry, Mapping) and isinstance(entry.get("value"), str):
            return normalise_text(entry["value"]) or None
    for entry in texts.values():
        if isinstance(entry, Mapping) and isinstance(entry.get("value"), str):
            return normalise_text(entry["value"]) or None
    return None


def _is_organisation(entity: Mapping[str, Any]) -> bool:
    claims = entity.get("claims")
    if not isinstance(claims, Mapping):
        return False
    if any(claims.get(prop) for prop in _COMPANY_PROPERTIES):
        return True
    return bool(_ORGANISATION_CLASSES.intersection(_item_ids(entity, P_INSTANCE_OF)))


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


class WikidataRegistry:
    name: RegistryName = "wikidata"

    def __init__(
        self, http: PoliteHttpClient, cache: RegistryCache, api_url: str = WIKIDATA_API_URL
    ) -> None:
        self._http = http
        self._cache = cache
        self._api_url = api_url

    async def _call(self, params: Mapping[str, str]) -> Mapping[str, Any]:
        for attempt in range(TRANSIENT_RETRIES + 1):
            answer = await self._http.get_json(self._api_url, {**params, "format": "json"})
            try:
                return _check(answer)
            except _TransientError as error:
                if attempt == TRANSIENT_RETRIES:
                    raise RegistryUnavailable("wikidata", f"API error {error}") from error
                self._http.back_off(TRANSIENT_PAUSE_SECONDS * 2**attempt)
        raise RegistryUnavailable("wikidata", "API error")  # pragma: no cover

    async def _search_ids(self, name: str, language: str) -> list[str]:
        answer = await self._call(
            {
                "action": "wbsearchentities",
                "search": name,
                "language": language,
                "uselang": language,
                "type": "item",
                "limit": str(SEARCH_LIMIT),
            }
        )
        results = answer.get("search")
        if not isinstance(results, list):
            raise RegistryUnavailable("wikidata", "unexpected search answer")
        return [r["id"] for r in results if isinstance(r, Mapping) and isinstance(r.get("id"), str)]

    async def _get_entities(
        self, ids: Sequence[str], props: str, languages: Sequence[str]
    ) -> dict[str, Mapping[str, Any]]:
        entities: dict[str, Mapping[str, Any]] = {}
        for start in range(0, len(ids), GET_ENTITIES_BATCH):
            answer = await self._call(
                {
                    "action": "wbgetentities",
                    "ids": "|".join(ids[start : start + GET_ENTITIES_BATCH]),
                    "props": props,
                    "languages": "|".join(languages),
                }
            )
            found = answer.get("entities")
            if not isinstance(found, Mapping):
                raise RegistryUnavailable("wikidata", "unexpected entities answer")
            for entity_id, entity in found.items():
                if isinstance(entity, Mapping) and "missing" not in entity:
                    entities[entity_id] = entity
        return entities

    async def _labels(self, ids: Sequence[str], languages: Sequence[str]) -> dict[str, str]:
        language_key = "|".join(languages)
        labels: dict[str, str] = {}
        missing: list[str] = []
        for item_id in ids:
            cached = self._cache.get(f"wikidata:label:{language_key}:{item_id}")
            if isinstance(cached, str):
                if cached:
                    labels[item_id] = cached
            else:
                missing.append(item_id)
        if missing:
            entities = await self._get_entities(missing, "labels", languages)
            for item_id in missing:
                label = _text_in(entities.get(item_id, {}).get("labels"), languages) or ""
                # An empty string records "no label" so that the item is not asked for again.
                self._cache.set(f"wikidata:label:{language_key}:{item_id}", label)
                if label:
                    labels[item_id] = label
        return labels

    async def _country_code(self, country_id: str) -> str | None:
        key = f"wikidata:country-code:{country_id}"
        cached = self._cache.get(key)
        if isinstance(cached, str):
            return cached or None
        answer = await self._call(
            {"action": "wbgetclaims", "entity": country_id, "property": P_ISO_ALPHA_2}
        )
        codes = _strings(answer, P_ISO_ALPHA_2)
        code = (normalise_code(codes[0]) if codes else None) or ""
        self._cache.set(key, code)
        return code or None

    async def search(self, name: str) -> list[RegistryCandidate]:
        languages = search_languages(name)
        id_lists = await asyncio.gather(*(self._search_ids(name, lang) for lang in languages))
        ids = _unique(item_id for id_list in id_lists for item_id in id_list)[:MAX_ENTITIES]
        if not ids:
            return []

        entities = await self._get_entities(ids, "labels|descriptions|claims", languages)
        companies = [entities[i] for i in ids if i in entities and _is_organisation(entities[i])]

        country_ids = _unique(c for e in companies for c in _item_ids(e, P_COUNTRY)[:1])
        referenced = _unique(
            [
                *country_ids,
                *(i for e in companies for i in _item_ids(e, P_INDUSTRY)),
                *(i for e in companies for i in _item_ids(e, P_LEGAL_FORM)[:1]),
            ]
        )
        labels, codes = await asyncio.gather(
            self._labels(referenced, languages),
            asyncio.gather(*(self._country_code(c) for c in country_ids)),
        )
        country_codes = dict(zip(country_ids, codes, strict=True))

        candidates: list[RegistryCandidate] = []
        for entity in companies:
            label = _text_in(entity.get("labels"), languages)
            entity_id = entity.get("id")
            if not label or not isinstance(entity_id, str):
                continue
            country_id = next(iter(_item_ids(entity, P_COUNTRY)), None)
            legal_form_id = next(iter(_item_ids(entity, P_LEGAL_FORM)), None)
            websites = _strings(entity, P_WEBSITE)
            leis = _strings(entity, P_LEI)
            candidates.append(
                RegistryCandidate(
                    name=label,
                    description=_text_in(entity.get("descriptions"), languages),
                    website=websites[0] if websites else None,
                    country=country_codes.get(country_id) if country_id else None,
                    country_name=labels.get(country_id) if country_id else None,
                    industries=tuple(
                        labels[i] for i in _unique(_item_ids(entity, P_INDUSTRY)) if i in labels
                    ),
                    legal_form=labels.get(legal_form_id) if legal_form_id else None,
                    wikidata_id=entity_id,
                    lei=leis[0].upper() if leis else None,
                    registries=("wikidata",),
                )
            )
        return candidates
