"""#134: the country the buyer states in the identity chat wins over the registry's."""

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import SupplierIdentity
from tests.identity.support import found, proposal
from tests.identity.test_identity import ACME, ACME_ID, setup


def test_a_country_stated_in_the_chat_replaces_the_registry_country_at_confirmation(
    engine: Engine, settings: Settings
) -> None:
    """The buyer writes that the supplier is German; the registry says France."""
    _harness, member = setup(
        engine,
        settings,
        found(ACME),
        model=[proposal(ACME_ID), proposal(ACME_ID, country_hint="de")],
    )
    session = member.open()
    after = member.call(
        "POST",
        f"/identity-sessions/{session['id']}/messages",
        json={"text": "It is a German company."},
    ).json()
    assert after["hints"] == {"website": None, "country": None, "sector": None}  # not exposed

    response = member.call(
        "POST", f"/identity-sessions/{session['id']}/confirm", json={"candidate_id": ACME_ID}
    )

    assert response.status_code == 200
    with Session(engine) as db:
        assert db.scalars(select(SupplierIdentity)).one().country == "DE"


def test_a_stated_country_equal_to_the_registry_one_changes_nothing(
    engine: Engine, settings: Settings
) -> None:
    _harness, member = setup(
        engine,
        settings,
        found(ACME),
        model=[proposal(ACME_ID), proposal(ACME_ID, country_hint="fr")],
    )
    session = member.open()
    member.call(
        "POST", f"/identity-sessions/{session['id']}/messages", json={"text": "France, yes."}
    )

    member.call(
        "POST", f"/identity-sessions/{session['id']}/confirm", json={"candidate_id": ACME_ID}
    )

    with Session(engine) as db:
        assert db.scalars(select(SupplierIdentity)).one().country == "FR"


def test_without_a_stated_country_the_registry_country_is_kept(
    engine: Engine, settings: Settings
) -> None:
    _harness, member = setup(
        engine, settings, found(ACME), model=[proposal(ACME_ID), proposal(ACME_ID)]
    )
    session = member.open()
    member.call(
        "POST", f"/identity-sessions/{session['id']}/messages", json={"text": "Yes, that one."}
    )

    member.call(
        "POST", f"/identity-sessions/{session['id']}/confirm", json={"candidate_id": ACME_ID}
    )

    with Session(engine) as db:
        assert db.scalars(select(SupplierIdentity)).one().country == "FR"
