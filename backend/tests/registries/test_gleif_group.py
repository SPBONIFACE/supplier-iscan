"""#142: GLEIF entity and group lookups (answers mocked, no network)."""

import asyncio

import pytest

from app.registries.cache import InMemoryRegistryCache
from app.registries.gleif_group import GleifGroupClient
from app.registries.http import FetchError, PoliteHttpClient, RegistryUnavailable
from tests.registries.gleif_support import (
    CHILD_LEI,
    PARENT_LEI,
    SUB_LEI,
    FakeGleif,
    group_answers,
    lei_record,
    many,
    one,
)


def client_over(fake: FakeGleif) -> GleifGroupClient:
    http = PoliteHttpClient("gleif", fake, {"User-Agent": "test"}, max_retries=0)
    return GleifGroupClient(http, InMemoryRegistryCache(60))


def test_the_record_is_read_with_its_place_and_forms() -> None:
    entity = asyncio.run(client_over(FakeGleif(group_answers())).record(SUB_LEI))

    assert entity is not None
    assert (entity.legal_name, entity.legal_form, entity.city, entity.country) == (
        "Acme France SAS",
        "SAS",
        "Paris",
        "FR",
    )
    assert entity.registered_as == "552 081 317"
    assert entity.legal_address == "1 Rue de la Paix, 75002 Paris, FR"
    assert entity.headquarters_address == "2 Avenue Foch, 75002 Paris, FR"
    assert entity.active and entity.candidate.registries == ("gleif",)


def test_the_ultimate_parent_wins_over_the_direct_parent() -> None:
    fake = FakeGleif(group_answers())

    parent = asyncio.run(client_over(fake).parent_of(SUB_LEI))

    assert parent is not None and parent.lei == PARENT_LEI
    assert fake.paths == [f"{SUB_LEI}/ultimate-parent"]  # one request


def test_without_an_ultimate_parent_the_direct_parent_is_used() -> None:
    answers = group_answers()
    del answers[f"{SUB_LEI}/ultimate-parent"]

    parent = asyncio.run(client_over(FakeGleif(answers)).parent_of(SUB_LEI))

    assert parent is not None and parent.lei == CHILD_LEI


def test_an_entity_that_is_its_own_parent_has_no_parent() -> None:
    answers = {
        f"{SUB_LEI}/ultimate-parent": one(lei_record(SUB_LEI, "Acme France SAS")),
        f"{SUB_LEI}/direct-parent": one(lei_record(SUB_LEI, "Acme France SAS")),
    }

    assert asyncio.run(client_over(FakeGleif(answers)).parent_of(SUB_LEI)) is None


def test_a_404_is_no_parent_and_a_failure_raises() -> None:
    assert asyncio.run(client_over(FakeGleif({})).parent_of(SUB_LEI)) is None
    server_error = client_over(FakeGleif({f"{SUB_LEI}/ultimate-parent": 500}))
    with pytest.raises(RegistryUnavailable):
        asyncio.run(server_error.parent_of(SUB_LEI))
    timeout = client_over(FakeGleif({f"{SUB_LEI}/ultimate-parent": FetchError("timeout")}))
    with pytest.raises(RegistryUnavailable):
        asyncio.run(timeout.parent_of(SUB_LEI))


def test_children_keep_the_active_ones_and_the_registers_total() -> None:
    client = client_over(FakeGleif(group_answers()))

    children = asyncio.run(client.ultimate_children(PARENT_LEI))

    assert children is not None
    assert [e.lei for e in children.entities] == [SUB_LEI, CHILD_LEI]
    assert children.total == 3


def test_children_are_capped_at_one_hundred() -> None:
    records = [lei_record(f"LEI{n:017d}", f"Acme {n} SAS") for n in range(120)]
    client = client_over(FakeGleif({f"{PARENT_LEI}/ultimate-children": many(*records)}))

    children = asyncio.run(client.ultimate_children(PARENT_LEI))

    assert children is not None and len(children.entities) == 100


def test_answers_and_missing_relations_are_cached() -> None:
    fake = FakeGleif(group_answers())
    client = client_over(fake)

    async def ask() -> None:
        await client.parent_of(SUB_LEI)
        await client.parent_of(SUB_LEI)
        await client.ultimate_parent("5299000NOBODY0000000")
        await client.ultimate_parent("5299000NOBODY0000000")

    asyncio.run(ask())

    assert fake.paths == [f"{SUB_LEI}/ultimate-parent", "5299000NOBODY0000000/ultimate-parent"]
