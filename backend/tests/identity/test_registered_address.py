"""A sole trader's registry address (#19, owner decision of 2 Nov 2026): kept for redaction only."""

import logging

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import IdentitySession, SupplierIdentity
from tests.identity.support import candidate, found, proposal
from tests.identity.test_identity import ACME_ID, setup

ADDRESS = "14 Rue des Lilas, 69003 Lyon, France"
SOLE_TRADER = candidate(
    "Jeanne Corvisier",
    legal_name="Jeanne Corvisier",
    legal_form="Entrepreneur individuel",
    registered_address=ADDRESS,
)
COMPANY = candidate(registered_address="3 Quai des Brumes, 13001 Marseille, France")


def _confirm(member: object, session_id: str) -> dict[str, object]:
    response = member.call(  # type: ignore[attr-defined]
        "POST", f"/identity-sessions/{session_id}/confirm", json={"candidate_id": ACME_ID}
    )
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


def test_a_sole_traders_registry_address_is_stored_on_the_identity(
    engine: Engine, settings: Settings
) -> None:
    _harness, member = setup(engine, settings, found(SOLE_TRADER), model=[proposal(ACME_ID)])
    session = member.open()

    _confirm(member, session["id"])

    with Session(engine) as db:
        identity = db.scalars(select(SupplierIdentity)).one()
        assert identity.natural_person is True
        assert identity.registered_address == ADDRESS


def test_a_companys_registry_address_is_not_stored(engine: Engine, settings: Settings) -> None:
    _harness, member = setup(engine, settings, found(COMPANY), model=[proposal(ACME_ID)])
    session = member.open()

    _confirm(member, session["id"])

    with Session(engine) as db:
        assert db.scalars(select(SupplierIdentity)).one().registered_address is None
        entries = db.scalars(select(IdentitySession)).one().candidates
    assert "Quai des Brumes" not in str(entries) and "Marseille" not in str(entries)


def test_a_sole_trader_without_a_registry_address_stores_none(
    engine: Engine, settings: Settings
) -> None:
    sole = candidate("Jeanne Corvisier", legal_name="Jeanne Corvisier", legal_form="Sole trader")
    _harness, member = setup(engine, settings, found(sole), model=[proposal(ACME_ID)])
    session = member.open()

    _confirm(member, session["id"])

    with Session(engine) as db:
        identity = db.scalars(select(SupplierIdentity)).one()
        assert identity.natural_person is True and identity.registered_address is None


def test_the_address_is_in_no_response_and_no_log(
    engine: Engine, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    _harness, member = setup(engine, settings, found(SOLE_TRADER), model=[proposal(ACME_ID)])
    session = member.open()
    seen = [
        str(session),
        str(member.call("GET", f"/identity-sessions/{session['id']}").json()),
        str(member.call("GET", f"/identity-sessions/{session['id']}/candidates").json()),
        str(_confirm(member, session["id"])),
    ]

    assert all("Lilas" not in text and "69003" not in text for text in seen)
    assert "Lilas" not in caplog.text and "69003" not in caplog.text


def test_the_address_never_reaches_the_model_even_when_the_member_types_it(
    engine: Engine, settings: Settings
) -> None:
    harness, member = setup(
        engine, settings, found(SOLE_TRADER), model=[proposal(ACME_ID), proposal(ACME_ID)]
    )
    session = member.open()

    member.call(
        "POST",
        f"/identity-sessions/{session['id']}/messages",
        json={"text": "She works from 14, rue des lilas 69003 LYON, I think."},
    )

    for request in harness.model.calls:
        assert "lilas" not in request.data.text.lower()
        assert "69003" not in request.data.text
