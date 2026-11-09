"""GLEIF candidates: legal name, LEI, registered address, legal form (spec, Integrations).

One request per search: ``GET /api/v1/lei-records?filter[entity.names]=…`` (legal name, other
names and transliterated names), throttled below 60 requests per minute by the HTTP layer.
"""

from collections.abc import Mapping
from typing import Any

from app.countries import normalise_code
from app.registries.http import PoliteHttpClient, RegistryUnavailable
from app.registries.models import RegistryCandidate, RegistryName
from app.registries.text import normalise_text

GLEIF_API_URL = "https://api.gleif.org/api/v1/lei-records"
PAGE_SIZE = 10


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return normalise_text(value) or None


def _address(address: Any) -> str | None:
    if not isinstance(address, Mapping):
        return None
    lines = address.get("addressLines")
    parts = [_text(line) for line in lines] if isinstance(lines, list) else []
    postal_code, city = _text(address.get("postalCode")), _text(address.get("city"))
    locality = " ".join(p for p in (postal_code, city) if p)
    parts.extend([locality or None, _text(address.get("country"))])
    joined = ", ".join(p for p in parts if p)
    return joined or None


def _candidate(record: Any) -> RegistryCandidate | None:
    if not isinstance(record, Mapping):
        return None
    attributes = record.get("attributes")
    if not isinstance(attributes, Mapping):
        return None
    entity = attributes.get("entity")
    lei = _text(attributes.get("lei"))
    if not isinstance(entity, Mapping) or not lei:
        return None
    legal_name_block = entity.get("legalName")
    legal_name = (
        _text(legal_name_block.get("name")) if isinstance(legal_name_block, Mapping) else None
    )
    if not legal_name:
        return None
    legal_address = entity.get("legalAddress")
    country = _text(legal_address.get("country")) if isinstance(legal_address, Mapping) else None
    legal_form = entity.get("legalForm")
    form_code = _text(legal_form.get("id")) if isinstance(legal_form, Mapping) else None
    form_other = _text(legal_form.get("other")) if isinstance(legal_form, Mapping) else None
    return RegistryCandidate(
        name=legal_name,
        legal_name=legal_name,
        country=normalise_code(country),
        legal_form=form_other,
        legal_form_code=form_code,
        registered_address=_address(legal_address),
        lei=lei.upper(),
        lei_status=_text(entity.get("status")),
        registries=("gleif",),
    )


# Public names of the helpers above, for the group lookups of ``app.registries.gleif_group``.
address_text = _address
candidate_from_record = _candidate
clean_text = _text


class GleifRegistry:
    name: RegistryName = "gleif"

    def __init__(self, http: PoliteHttpClient, api_url: str = GLEIF_API_URL) -> None:
        self._http = http
        self._api_url = api_url

    async def search(self, name: str) -> list[RegistryCandidate]:
        answer = await self._http.get_json(
            self._api_url, {"filter[entity.names]": name, "page[size]": str(PAGE_SIZE)}
        )
        if not isinstance(answer, Mapping) or not isinstance(answer.get("data"), list):
            raise RegistryUnavailable("gleif", "unexpected answer")
        candidates: list[RegistryCandidate] = []
        seen: set[str] = set()
        for record in answer["data"]:
            candidate = _candidate(record)
            if candidate is not None and candidate.lei not in seen:
                seen.add(candidate.lei or "")
                candidates.append(candidate)
        return candidates
