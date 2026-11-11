"""GLEIF entity and group lookups: one record, its parents and its ultimate children (#142).

Public data of the LEI register, read through the polite HTTP client of the GLEIF search (so the
same rate limit applies) and cached by LEI. A 404 means "no such record or relation" and gives
``None``; any other failure raises ``RegistryUnavailable`` and the caller carries on without it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.registries.cache import JsonValue, RegistryCache
from app.registries.gleif import GLEIF_API_URL, address_text, candidate_from_record, clean_text
from app.registries.http import PoliteHttpClient, RegistryUnavailable
from app.registries.models import RegistryCandidate

CHILDREN_PAGE_SIZE = 100
NOT_FOUND = "HTTP 404"
_MISSING: JsonValue = {"missing": True}


@dataclass(frozen=True)
class GleifEntity:
    lei: str
    legal_name: str
    legal_form: str | None  # the free text (legalForm.other), when the record has it
    legal_form_code: str | None  # the ELF code (legalForm.id); GLEIF gives no name for it
    registered_as: str | None
    status: str | None
    legal_address: str | None
    headquarters_address: str | None
    city: str | None
    country: str | None
    candidate: RegistryCandidate

    @property
    def active(self) -> bool:
        return (self.status or "").upper() == "ACTIVE"

    def place(self) -> str:
        """``<city>, <country>``, whichever is known."""
        return ", ".join(part for part in (self.city, self.country) if part)


@dataclass(frozen=True)
class GleifChildren:
    entities: tuple[GleifEntity, ...]
    # The register's own count of ultimate children, when it gives one.
    total: int | None


def _locality(entity: Mapping[str, Any], key: str, field: str) -> str | None:
    block = entity.get(key)
    return clean_text(block.get(field)) if isinstance(block, Mapping) else None


def parse_entity(record: Any) -> GleifEntity | None:
    """A GLEIF ``lei-records`` item as an entity, or None when it lacks a LEI or a legal name."""
    candidate = candidate_from_record(record)
    if candidate is None or not candidate.lei or not candidate.legal_name:
        return None
    entity: Mapping[str, Any] = record["attributes"]["entity"]
    legal_form = entity.get("legalForm")
    form = code = None
    if isinstance(legal_form, Mapping):
        form = clean_text(legal_form.get("other"))
        code = clean_text(legal_form.get("id"))
    city = _locality(entity, "legalAddress", "city") or _locality(
        entity, "headquartersAddress", "city"
    )
    country = _locality(entity, "legalAddress", "country") or _locality(
        entity, "headquartersAddress", "country"
    )
    return GleifEntity(
        lei=candidate.lei,
        legal_name=candidate.legal_name,
        legal_form=form,
        legal_form_code=code,
        registered_as=clean_text(entity.get("registeredAs")),
        status=candidate.lei_status,
        legal_address=address_text(entity.get("legalAddress")),
        headquarters_address=address_text(entity.get("headquartersAddress")),
        city=city,
        country=country.upper() if country else None,
        candidate=candidate,
    )


class GleifGroupClient:
    def __init__(
        self, http: PoliteHttpClient, cache: RegistryCache, api_url: str = GLEIF_API_URL
    ) -> None:
        self._http = http
        self._cache = cache
        self._api_url = api_url

    async def _get(
        self, path: str, params: Mapping[str, str] | None = None
    ) -> Mapping[str, Any] | None:
        key = f"gleif:group:{path}:{sorted((params or {}).items())}"
        cached = self._cache.get(key)
        if isinstance(cached, dict):
            return None if cached == _MISSING else cached
        try:
            answer = await self._http.get_json(f"{self._api_url}/{path}", params or {})
        except RegistryUnavailable as error:
            if error.reason == NOT_FOUND:
                self._cache.set(key, _MISSING)
                return None
            raise
        if not isinstance(answer, Mapping):
            raise RegistryUnavailable("gleif", "unexpected answer")
        self._cache.set(key, dict(answer))
        return answer

    async def _one(self, path: str) -> GleifEntity | None:
        answer = await self._get(path)
        return parse_entity(answer.get("data")) if answer is not None else None

    async def record(self, lei: str) -> GleifEntity | None:
        return await self._one(lei)

    async def ultimate_parent(self, lei: str) -> GleifEntity | None:
        return await self._one(f"{lei}/ultimate-parent")

    async def direct_parent(self, lei: str) -> GleifEntity | None:
        return await self._one(f"{lei}/direct-parent")

    async def parent_of(self, lei: str) -> GleifEntity | None:
        """The ultimate parent, or the direct parent when there is none; None when the entity is
        its own top or has no known parent."""
        parent = await self.ultimate_parent(lei)
        if parent is None or parent.lei == lei:
            parent = await self.direct_parent(lei)
        return parent if parent is not None and parent.lei != lei else None

    async def ultimate_children(self, lei: str) -> GleifChildren | None:
        answer = await self._get(
            f"{lei}/ultimate-children", {"page[size]": str(CHILDREN_PAGE_SIZE)}
        )
        if answer is None:
            return None
        data = answer.get("data")
        if not isinstance(data, list):
            raise RegistryUnavailable("gleif", "unexpected answer")
        entities = [e for e in (parse_entity(item) for item in data) if e is not None]
        active = tuple(e for e in entities if e.active)[:CHILDREN_PAGE_SIZE]
        meta = answer.get("meta")
        pagination = meta.get("pagination") if isinstance(meta, Mapping) else None
        total = pagination.get("total") if isinstance(pagination, Mapping) else None
        return GleifChildren(active, total if isinstance(total, int) else None)
