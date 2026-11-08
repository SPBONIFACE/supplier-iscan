"""#136: the country is stored as an ISO alpha-2 code everywhere and shown as the full name."""

import copy
import json
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.collection.retrieval import IdentityRecord, _supplier_text
from app.config import Settings
from app.countries import code_for_name, country_name, normalise_code
from app.financial.guidance import build_guidance
from app.financial.table import EXAMPLE_FILE, load_country_table
from app.migrate import alembic_config
from app.models import SupplierIdentity
from app.pdf.render import render_html
from app.registries import RegistryCandidate
from tests.factories import create_user
from tests.identity.support import candidate, found, proposal
from tests.identity.test_identity import setup
from tests.pdf.support import card, run_out
from tests.runs_support import create_identity

# --- the name table ---------------------------------------------------------------------------


def test_a_code_is_shown_as_the_full_name_in_each_language() -> None:
    assert country_name("DE", "en") == "Germany"
    assert country_name("de", "fr") == "Allemagne"


def test_an_unknown_code_is_shown_as_the_code() -> None:
    assert country_name("ZZ", "en") == "ZZ"
    assert country_name(None) is None


def test_codes_are_normalised_upper_case_and_free_text_is_no_code() -> None:
    assert normalise_code(" de ") == "DE"
    assert normalise_code("Germany") is None
    assert normalise_code("D1") is None
    assert normalise_code(None) is None


def test_an_english_or_french_name_maps_to_its_code_when_unambiguous() -> None:
    assert code_for_name("France") == "FR"
    assert code_for_name("Allemagne") == "DE"
    assert code_for_name("côte d’ivoire") == "CI"
    assert code_for_name("Atlantis") is None
    assert code_for_name("") is None


# --- registry candidates ----------------------------------------------------------------------


def test_a_registry_candidate_carries_a_code_never_a_free_text_name() -> None:
    assert (
        RegistryCandidate(
            name="A", country="de", wikidata_id="Q1", registries=("wikidata",)
        ).country
        == "DE"
    )
    assert (
        RegistryCandidate(
            name="A", country="Germany", wikidata_id="Q1", registries=("wikidata",)
        ).country
        is None
    )


def test_a_wikidata_candidate_is_shown_to_the_buyer_with_the_code(
    engine: Engine, settings: Settings
) -> None:
    german = candidate(
        "Beispiel GmbH", country="DE", country_name="Germany", lei=None, registries=("wikidata",)
    )
    _harness, member = setup(engine, settings, found(german), model=[proposal("wd:Q1")])

    session = member.open()

    assert session["turns"][-1]["candidate"]["country"] == "DE"


def test_a_candidate_without_a_code_has_no_country_even_with_a_label(
    engine: Engine, settings: Settings
) -> None:
    labelled = candidate("Beispiel GmbH", country=None, country_name="Germany", lei=None)
    _harness, member = setup(engine, settings, found(labelled), model=[proposal("wd:Q1")])

    session = member.open()

    assert session["turns"][-1]["candidate"]["country"] is None


# --- the financial guidance finds the row for a Wikidata-confirmed supplier --------------------


def test_a_german_supplier_confirmed_from_a_wikidata_candidate_gets_the_de_row(
    engine: Engine, settings: Settings, tmp_path: Path
) -> None:
    german = candidate(
        "Beispiel GmbH", country="DE", country_name="Germany", lei=None, registries=("wikidata",)
    )
    _harness, member = setup(engine, settings, found(german), model=[proposal("wd:Q1")])
    session = member.open()
    response = member.call(
        "POST",
        f"/identity-sessions/{session['id']}/confirm",
        json={"candidate_id": "wd:Q1"},
    )
    assert response.status_code == 200, response.text
    with Session(engine) as db:
        stored = db.scalars(select(SupplierIdentity)).one().country
    assert stored == "DE"

    document = json.loads(EXAMPLE_FILE.read_text(encoding="utf-8"))
    row = copy.deepcopy(document["countries"][0])
    row["country"] = "DE"
    document["countries"] = [row]
    path = tmp_path / "countries.json"
    path.write_text(json.dumps(document))
    table = load_country_table(path)
    guidance = build_guidance(table, stored, "en", 2025, natural_person=False)

    assert guidance is not None and guidance.configured is True and guidance.country == "DE"


# --- display ------------------------------------------------------------------------------------


@pytest.mark.parametrize(("lang", "expected"), [("en", "Germany"), ("fr", "Allemagne")])
def test_the_pdf_shows_the_full_country_name_in_the_requested_language(
    lang: str, expected: str
) -> None:
    html = render_html(card(lang, run=run_out(supplier_country="DE")))  # type: ignore[arg-type]

    assert expected in html
    assert ">DE<" not in html


def test_the_pdf_shows_an_unknown_code_as_the_code() -> None:
    html = render_html(card("en", run=run_out(supplier_country="ZZ")))

    assert "ZZ" in html


def test_the_retrieval_request_names_the_country() -> None:
    text = _supplier_text(IdentityRecord("Acme", None, "DE"), [])

    assert "Country: Germany (DE)" in text


# --- the migration ------------------------------------------------------------------------------


def test_the_migration_turns_unambiguous_names_into_codes_and_leaves_the_rest(
    engine: Engine,
) -> None:
    user = create_user(engine)
    values = ["France", "Allemagne", "de", "DE", "Atlantis", None]
    for value in values:
        create_identity(engine, user.organisation_id, country=value)
    # The schema is at head: step back over this (one-way) migration and apply it to the rows.
    with engine.connect() as connection:
        config = alembic_config(connection)
        command.downgrade(config, "a9c2e5f81d34")
        command.upgrade(config, "head")
        connection.commit()

    with Session(engine) as db:
        stored = sorted((c or "") for c in db.scalars(select(SupplierIdentity.country)).all())
    assert stored == sorted(["FR", "DE", "DE", "DE", "Atlantis", ""])
