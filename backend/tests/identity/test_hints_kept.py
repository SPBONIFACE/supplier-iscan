"""The buyer's country and sector hints fill a candidate that has none of its own (#187).

A value filled from a hint is listed in `given_by_buyer`; a value a registry gave is never replaced.
"""

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.financial.guidance import Observations, build_guidance
from app.financial.table import load_country_table
from app.models import SupplierIdentity
from tests.identity.support import WEBSITE_HOST, candidate, found, proposal
from tests.identity.test_identity import ACME, ACME_ID, setup

WEB_ID = f"web:{WEBSITE_HOST}"
SECTOR = "Plastic closure manufacturer (packaging)"
HINTS = {"website": f"https://{WEBSITE_HOST}", "country": "CH", "sector": SECTOR}


def test_a_website_candidate_takes_the_buyers_country_and_sector(
    engine: Engine, settings: Settings
) -> None:
    _harness, member = setup(engine, settings, found())

    session = member.open(hints=HINTS)

    shown = session["turns"][-1]["candidate"]
    assert shown["id"] == WEB_ID and shown["found_in"] == ["website"]
    assert shown["country"] == "CH" and shown["sector"] == SECTOR
    assert shown["given_by_buyer"] == ["country", "sector"]


def test_the_confirmed_country_reaches_the_financial_guidance(
    engine: Engine, settings: Settings
) -> None:
    _harness, member = setup(engine, settings, found())
    session = member.open(hints=HINTS)

    confirmed = member.call(
        "POST", f"/identity-sessions/{session['id']}/confirm", json={"candidate_id": WEB_ID}
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["candidate"]["country"] == "CH"
    with Session(engine) as db:
        identity = db.scalars(select(SupplierIdentity)).one()
        assert (identity.country, identity.sector) == ("CH", SECTOR)
    guidance = build_guidance(
        load_country_table(),
        identity.country,
        "en",
        2025,
        natural_person=False,
        observations=Observations(),
    )
    assert guidance is not None
    assert guidance.country == "CH"


def test_a_registry_value_is_never_overwritten_by_a_hint(
    engine: Engine, settings: Settings
) -> None:
    _harness, member = setup(engine, settings, found(ACME), model=[proposal(ACME_ID)])

    session = member.open(hints={"country": "FR", "sector": SECTOR})

    shown = session["turns"][-1]["candidate"]
    assert shown["id"] == ACME_ID
    assert shown["country"] == "FR" and shown["sector"] == "Wholesale"  # the registry's
    assert shown["given_by_buyer"] == []


def test_without_hints_nothing_is_filled(engine: Engine, settings: Settings) -> None:
    _harness, member = setup(engine, settings, found())

    session = member.open(hints={"website": f"https://{WEBSITE_HOST}"})

    shown = session["turns"][-1]["candidate"]
    assert shown["country"] is None and shown["sector"] is None
    assert shown["given_by_buyer"] == []


def test_a_registry_candidate_without_country_or_sector_takes_the_hints(
    engine: Engine, settings: Settings
) -> None:
    bare = candidate(
        "Bare SA",
        legal_name="Bare SA",
        country=None,
        country_name=None,
        industries=(),
        lei="5299BARE0000000000AA",
        wikidata_id="Q9",
    )
    bare_id = "lei:5299BARE0000000000AA"
    _harness, member = setup(engine, settings, found(bare), model=[proposal(bare_id)])

    session = member.open(hints={"country": "CH", "sector": SECTOR})

    shown = session["turns"][-1]["candidate"]
    assert shown["country"] == "CH" and shown["sector"] == SECTOR
    assert shown["given_by_buyer"] == ["country", "sector"]
