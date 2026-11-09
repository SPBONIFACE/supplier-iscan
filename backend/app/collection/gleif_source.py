"""The GLEIF source of a run (#142): the confirmed entity's LEI record and its group, as one source.

Built from the public LEI register before the website is collected, so that it is the first source
the extraction reads (it is fetched, hence stored, first) and its values are preferred for the
identity fields. The text is plain, labelled lines. The polite GLEIF client and its cache are
those of the registry search. When GLEIF is unavailable or slow the run goes on without this
source and the failure log says so.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from app.collection.failures import Failure, Kind, make_failure
from app.collection.source_store import SourceRecord
from app.db import utc_now
from app.http_client import GuardedClient
from app.registries.cache import InMemoryRegistryCache, RegistryCache
from app.registries.gleif_group import GleifChildren, GleifEntity, GleifGroupClient
from app.registries.guarded_fetch import GuardedFetch
from app.registries.http import Fetch, RegistryUnavailable
from app.registries.service import build_gleif_group_client
from app.registries.settings import RegistrySettings, load_registry_settings

logger = logging.getLogger(__name__)

RECORD_PAGE = "https://search.gleif.org/#/record/{lei}"
# Upper bound for all the GLEIF requests of one run, on top of the per-request timeout.
TIMEOUT_FACTOR = 3
UNAVAILABLE_MESSAGE = (
    "The GLEIF record of the supplier could not be read, so the run went on without it."
)

_cache: RegistryCache | None = None


def record_page(lei: str) -> str:
    return RECORD_PAGE.format(lei=lei)


def shared_cache(settings: RegistrySettings) -> RegistryCache:
    """One cache for the process: a group is read once per day, not once per run."""
    global _cache  # noqa: PLW0603
    if _cache is None:
        _cache = InMemoryRegistryCache(settings.cache_ttl_seconds)
    return _cache


@dataclass(frozen=True)
class GleifGroup:
    entity: GleifEntity
    direct_parent: GleifEntity | None
    ultimate_parent: GleifEntity | None
    children: GleifChildren | None


def _label(label: str, value: str | None) -> str | None:
    return f"{label}: {value}" if value else None


def _party(entity: GleifEntity) -> str:
    place = f" ({entity.place()})" if entity.place() else ""
    return f"{entity.legal_name}{place}, LEI {entity.lei}"


def group_entities(group: GleifGroup) -> list[GleifEntity]:
    """The entity, its parents' and children's records without duplicates; active ones only for
    the children (the entity and its parents are listed whatever their status)."""
    seen: dict[str, GleifEntity] = {}
    for item in (
        group.ultimate_parent,
        group.entity,
        *(group.children.entities if group.children else ()),
    ):
        if item is not None:
            seen.setdefault(item.lei, item)
    return list(seen.values())


def render_group(group: GleifGroup) -> str:
    entity = group.entity
    lines: list[str | None] = [
        _label("Legal name", entity.legal_name),
        _label("LEI", entity.lei),
        _label("Entity status", entity.status),
        _label("Legal form", entity.legal_form),
        _label("Registration authority entity ID", entity.registered_as),
        _label("Legal address", entity.legal_address),
        _label("Headquarters address", entity.headquarters_address),
        _label("Direct parent", _party(group.direct_parent) if group.direct_parent else None),
        _label("Ultimate parent", _party(group.ultimate_parent) if group.ultimate_parent else None),
    ]
    if group.children is not None:
        members = group_entities(group)
        countries = {m.country for m in members if m.country}
        lines.append(
            f"Group entities registered with an LEI: {len(members)} in {len(countries)} countries"
        )
        if group.children.total is not None and group.children.total > len(group.children.entities):
            lines.append(
                f"Listed: the first {len(group.children.entities)} active ultimate children "
                f"of {group.children.total}"
            )
        lines.extend(f"{m.legal_name}, {m.city or '-'}, {m.country or '-'}" for m in members)
    return "\n".join(line for line in lines if line)


async def fetch_group(client: GleifGroupClient, lei: str) -> GleifGroup | None:
    """The record and its group. None when the record itself is missing; raises
    ``RegistryUnavailable`` when it cannot be read. A parent or children lookup that fails only
    leaves its lines out."""
    entity = await client.record(lei)
    if entity is None:
        return None

    async def optional[T](lookup: Coroutine[Any, Any, T | None]) -> T | None:
        try:
            return await lookup
        except RegistryUnavailable as error:
            logger.info("GLEIF group lookup skipped: %s", error.reason)
            return None

    direct = await optional(client.direct_parent(lei))
    ultimate = await optional(client.ultimate_parent(lei))
    top = ultimate.lei if ultimate is not None and ultimate.lei != lei else lei
    children = await optional(client.ultimate_children(top))
    return GleifGroup(entity, direct, ultimate if top != lei else None, children)


def _failure(lei: str, error: Exception) -> Failure:
    reason = error.reason if isinstance(error, RegistryUnavailable) else "timeout"
    kind: Kind = "timeout" if reason == "timeout" else "unreachable"
    if reason.startswith("HTTP "):
        kind = "http_error"
    return make_failure(record_page(lei), "retrieval", kind, message=UNAVAILABLE_MESSAGE)


def gleif_source(
    lei: str,
    client: GleifGroupClient,
    settings: RegistrySettings | None = None,
) -> tuple[SourceRecord | None, Failure | None]:
    """The source of the entity with this LEI, or the failure to log when it could not be read.
    Neither when GLEIF has no record of it."""
    limits = settings or load_registry_settings()
    try:
        group = asyncio.run(
            asyncio.wait_for(fetch_group(client, lei), limits.timeout_seconds * TIMEOUT_FACTOR)
        )
    except (RegistryUnavailable, TimeoutError) as error:
        logger.warning("GLEIF source skipped: %s", type(error).__name__)
        return None, _failure(lei, error)
    if group is None:
        return None, make_failure(
            record_page(lei),
            "retrieval",
            "empty_content",
            message="No public evidence found: GLEIF has no record for this LEI.",
        )
    record = SourceRecord(record_page(lei), utc_now(), "text/plain", render_group(group))
    return record, None


def store_gleif_source(
    lei: str | None, store: Callable[[SourceRecord], None], fetch: Fetch | None = None
) -> Failure | None:
    """The small call at the start of collection: stores the GLEIF source first when the identity
    has an LEI. Returns the failure to log, if any. Never raises because of GLEIF. ``fetch`` is
    for tests; by default the guarded client of #15 is used."""
    if not lei:
        return None
    settings = load_registry_settings()

    def read(outbound: Fetch) -> tuple[SourceRecord | None, Failure | None]:
        client = build_gleif_group_client(settings, outbound, shared_cache(settings))
        return gleif_source(lei, client, settings)

    try:
        if fetch is not None:
            record, failure = read(fetch)
        else:
            with GuardedClient() as guarded:
                record, failure = read(GuardedFetch(guarded, settings.timeout_seconds))
    except Exception as error:  # noqa: BLE001 - GLEIF must never stop a run
        logger.warning("GLEIF source skipped: %s", type(error).__name__)
        record, failure = (
            None,
            make_failure(record_page(lei), "retrieval", "unreachable", message=UNAVAILABLE_MESSAGE),
        )
    if record is not None:
        store(record)
    return failure
