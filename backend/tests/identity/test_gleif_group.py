"""#142: the group of the proposed company, and the LEI attached at confirmation (GLEIF mocked)."""

from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.identity.candidates import comparable_name
from app.models import SupplierIdentity
from app.registries.gleif_group import GleifEntity, parse_entity
from tests.identity.support import candidate, found, proposal
from tests.identity.test_identity import Member, setup
from tests.registries.gleif_support import PARENT_LEI, SUB_LEI, lei_record

SUBSIDIARY = candidate(
    "Acme France SAS",
    legal_name="Acme France SAS",
    lei=SUB_LEI,
    wikidata_id=None,
    registries=("gleif",),
)
SUBSIDIARY_ID = f"lei:{SUB_LEI}"
PARENT = parse_entity(lei_record(PARENT_LEI, "Acme Holding GmbH", "Munich", "DE", form="GmbH"))


class FakeGroup:
    def __init__(self, parent: GleifEntity | None, error: Exception | None = None) -> None:
        self.parent = parent
        self.error = error
        self.asked: list[str] = []

    async def parent_of(self, lei: str) -> GleifEntity | None:
        self.asked.append(lei)
        if self.error is not None:
            raise self.error
        return self.parent


def open_with(
    engine: Engine, settings: Settings, group: FakeGroup | None, *candidates: Any
) -> tuple[Member, dict[str, Any]]:
    harness, member = setup(engine, settings, found(*candidates), model=[proposal(SUBSIDIARY_ID)])
    harness.services.group = group
    return member, member.open()


def proposal_turn(session: dict[str, Any]) -> dict[str, Any]:
    (turn,) = [t for t in session["turns"] if t["kind"] == "proposal"]
    return turn


def test_a_subsidiary_proposal_shows_its_group_and_offers_the_parent(
    engine: Engine, settings: Settings
) -> None:
    group = FakeGroup(PARENT)
    member, session = open_with(engine, settings, group, SUBSIDIARY)

    turn = proposal_turn(session)
    assert "Part of group: Acme Holding GmbH, Munich, DE" in turn["text"]
    assert turn["candidate"]["id"] == SUBSIDIARY_ID  # the proposal itself does not change
    others = member.call("GET", f"/identity-sessions/{session['id']}/candidates").json()
    assert [(c["id"], c["found_in"]) for c in others["candidates"]] == [
        (f"lei:{PARENT_LEI}", ["gleif"])
    ]
    assert group.asked == [SUB_LEI]  # one extra request for the proposed candidate


def test_the_group_line_follows_the_ui_language(engine: Engine, settings: Settings) -> None:
    harness, member = setup(engine, settings, found(SUBSIDIARY), model=[proposal(SUBSIDIARY_ID)])
    harness.services.group = FakeGroup(PARENT)

    session = member.open(ui_language="fr")

    assert "Fait partie du groupe : Acme Holding GmbH, Munich, DE" in proposal_turn(session)["text"]


def test_the_parent_can_be_confirmed(engine: Engine, settings: Settings) -> None:
    member, session = open_with(engine, settings, FakeGroup(PARENT), SUBSIDIARY)

    response = member.call(
        "POST",
        f"/identity-sessions/{session['id']}/confirm",
        json={"candidate_id": f"lei:{PARENT_LEI}"},
    )

    assert response.status_code == 200, response.text
    with Session(engine) as db:
        identity = db.scalars(select(SupplierIdentity)).one()
    assert identity.legal_name == "Acme Holding GmbH"
    assert identity.registry_ids == {"lei": PARENT_LEI}


@pytest.mark.parametrize(
    "group",
    [
        FakeGroup(None, RuntimeError("GLEIF down")),
        FakeGroup(None),  # a 404: no parent known
        FakeGroup(parse_entity(lei_record(SUB_LEI, "Acme France SAS"))),  # itself
        None,  # no lookup wired
    ],
)
def test_a_failing_or_empty_lookup_changes_nothing(
    engine: Engine, settings: Settings, group: FakeGroup | None
) -> None:
    member, session = open_with(engine, settings, group, SUBSIDIARY)

    turn = proposal_turn(session)
    assert "Part of group" not in turn["text"]
    assert turn["candidate"]["id"] == SUBSIDIARY_ID
    assert member.call("GET", f"/identity-sessions/{session['id']}/candidates").json() == {
        "candidates": []
    }
    assert session["registries"] == {"gleif": "ok", "wikidata": "ok"}


def test_a_candidate_without_an_lei_gets_no_lookup(engine: Engine, settings: Settings) -> None:
    group = FakeGroup(PARENT)
    wikidata_only = candidate(lei=None, registries=("wikidata",))
    harness, member = setup(engine, settings, found(wikidata_only), model=[proposal("wd:Q1")])
    harness.services.group = group

    session = member.open()

    assert group.asked == [] and "Part of group" not in proposal_turn(session)["text"]


# --- the LEI at confirmation ------------------------------------------------------------------

WIKIDATA = candidate(
    "Société Acme",
    legal_name="Société Acme",
    lei=None,
    wikidata_id="Q5",
    registries=("wikidata",),
)
TWIN = candidate(
    "SOCIETE ACME S.A.S.",
    legal_name="SOCIETE ACME S.A.S.",
    lei="5299000TWIN000000001",
    lei_status="ACTIVE",
    wikidata_id=None,
    registries=("gleif",),
)


def confirmed_ids(
    engine: Engine, settings: Settings, *candidates: Any, wanted: str = "wd:Q5"
) -> dict[str, Any]:
    _harness, member = setup(engine, settings, found(*candidates), model=[proposal(wanted)])
    session = member.open()
    response = member.call(
        "POST", f"/identity-sessions/{session['id']}/confirm", json={"candidate_id": wanted}
    )
    assert response.status_code == 200, response.text
    with Session(engine) as db:
        return dict(db.scalars(select(SupplierIdentity)).one().registry_ids)


def test_the_lei_of_the_unique_active_gleif_twin_is_attached(
    engine: Engine, settings: Settings
) -> None:
    ids = confirmed_ids(engine, settings, WIKIDATA, TWIN)

    assert ids == {"lei": "5299000TWIN000000001", "wikidata_id": "Q5"}


def test_two_matching_gleif_candidates_attach_no_lei(engine: Engine, settings: Settings) -> None:
    second = candidate(
        "Societe Acme SA",
        legal_name="Societe Acme SA",
        lei="5299000TWIN000000002",
        lei_status="ACTIVE",
        wikidata_id=None,
        registries=("gleif",),
    )

    assert confirmed_ids(engine, settings, WIKIDATA, TWIN, second) == {"wikidata_id": "Q5"}


@pytest.mark.parametrize(
    "twin",
    [
        {"country": "DE"},  # another country
        {"lei_status": "INACTIVE"},  # not active
        {"lei_status": None},  # status unknown
        {"name": "Societe Acme Holding", "legal_name": "Societe Acme Holding"},  # another name
    ],
)
def test_a_twin_in_another_country_inactive_or_differently_named_attaches_nothing(
    engine: Engine, settings: Settings, twin: dict[str, Any]
) -> None:
    other = candidate(
        **{
            "name": "Société Acme SAS",
            "legal_name": "Société Acme SAS",
            "lei": "5299000TWIN000000001",
            "lei_status": "ACTIVE",
            "wikidata_id": None,
            "registries": ("gleif",),
            **twin,
        }
    )

    assert confirmed_ids(engine, settings, WIKIDATA, other) == {"wikidata_id": "Q5"}


def test_a_candidate_that_has_an_lei_keeps_it(engine: Engine, settings: Settings) -> None:
    own = candidate(wikidata_id="Q9", lei="5299000OWN0000000001", registries=("wikidata", "gleif"))

    ids = confirmed_ids(engine, settings, own, TWIN, wanted="lei:5299000OWN0000000001")

    assert ids["lei"] == "5299000OWN0000000001"


def test_names_compare_without_case_accents_punctuation_and_form() -> None:
    assert comparable_name("Société Acme S.A.S.") == comparable_name("SOCIETE ACME")
    assert comparable_name("Acme GmbH & Co. KG") == "acme"
    assert comparable_name("Acme-Industries, Ltd.") == "acme industries"
    assert comparable_name("SA") == "sa"  # a name that is only a form word is kept
