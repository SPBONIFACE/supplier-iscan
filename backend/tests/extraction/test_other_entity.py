"""#209: a fact from a passage about another legal entity of the supplier's group.

Replays the Bericap test card of 26 Nov 2026: the confirmed entity is the French BERICAP (no legal
form in its legal name); a trade-press page about the German BERICAP GmbH & Co. KG gave the card
the legal form "GmbH & Co. KG", and a plant in Kunshan without a label.

The decision is code (`GroupEntities`, `Supplier.other_entity`, `judge`), never the model: most
cases call `judge` directly; the stage cases check what is stored and logged."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Engine

from app.extraction.grounding import fold, group_entities, named_companies, normalise
from app.extraction.settings import ExtractionSettings
from app.extraction.stage import Kept, SourceText, Supplier, Tally, judge
from app.llm_schemas import FieldExtraction
from app.profile_definition import FieldDefinition, load_profile_definition
from tests.extraction.support import Asked, add_source, facts_of, item, not_found, run_row, scripted
from tests.extraction.test_stage import run_stage, setup

ENTITY = "BERICAP"
GROUP = "BERICAP Holding GmbH"
WEBSITE = "https://www.bericap.com"
# Before the supplier's website in the canonical order of sources (fetched_at, url).
PRESS = "https://news.petnology.example/bericap-kunshan"
SISTER = "BERICAP GmbH & Co. KG"
PAGE = (
    "Closures for the pet food industry.\n"
    f"{SISTER}, the closure maker based in Budenheim, has opened a new production plant in "
    "Kunshan, China, and has acquired Embankment Plastics in Ireland."
)
PLANT_QUOTE = "has opened a new production plant in Kunshan, China"
PLANT = "Kunshan, China"

DEFINITION = load_profile_definition()
FIELDS: dict[str, FieldDefinition] = {f.id: f for f in DEFINITION.fields() if f.kind == "fact"}
LIMITS = ExtractionSettings()

BERICAP = Supplier(ENTITY, WEBSITE, "FR", group_name=GROUP)


def source(text: str, url: str = PRESS, source_type: str = "third_party") -> SourceText:
    return SourceText(
        id=uuid.uuid4(),
        url=url,
        fetched_at=datetime(2026, 11, 26, tzinfo=UTC),
        author=None,
        text=text,
        source_type=source_type,
        publisher="petnology.example",
        normalised=normalise(text),
        folded=fold(text),
    )


def judged(
    field: str,
    value: str,
    quote: str,
    text: str = PAGE,
    supplier: Supplier = BERICAP,
    url: str = PRESS,
    source_type: str = "third_party",
) -> tuple[Kept | None, Tally]:
    given = source(text, url, source_type)
    answer = FieldExtraction(
        field=field, status="found", value=value, quote=quote, source_id=str(given.id)
    )
    tally = Tally()
    return judge(answer, given, tally, FIELDS, LIMITS, supplier), tally


def legal_form(quote: str = SISTER, value: str = "GmbH & Co. KG", **given: Any) -> Any:
    return judged("legal_form", value, quote, **given)


def plant(quote: str = PLANT_QUOTE, value: str = PLANT, **given: Any) -> Any:
    return judged("production_sites", value, quote, **given)


# --- entity-specific fields never take another entity's value ---


def test_the_example_definition_marks_the_legal_form_alone_entity_specific() -> None:
    assert [f.id for f in DEFINITION.fields() if f.entity_specific] == ["legal_form"]


def test_the_bericap_case_the_sister_companys_legal_form_is_discarded() -> None:
    kept, tally = legal_form()

    assert kept is None
    assert tally.grounding_failures == 1 and tally.other_group_entity == 1
    assert tally.not_named_near_quote == 0 and tally.invalid_items == 0


def test_the_bericap_case_in_the_stage_a_later_source_fills_the_legal_form(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    organisation_id, run_id, _press = setup(
        engine, PAGE, PRESS, legal_name=ENTITY, website=WEBSITE, country="FR", group_name=GROUP
    )
    own = add_source(
        engine,
        organisation_id,
        run_id,
        f"{WEBSITE}/fr/mentions-legales",
        "Mentions légales. BERICAP SAS au capital de 1 000 000 euros, siège social à Longvic.",
    )

    def respond(asked: Asked) -> list[dict[str, Any]]:
        own_page = "Mentions" in asked.text
        out = []
        for name in asked.fields:
            if name == "legal_form" and own_page:
                out.append(item(name, "SAS", "BERICAP SAS au capital de", asked.source_id))
            elif name == "legal_form":
                out.append(item(name, "GmbH & Co. KG", SISTER, asked.source_id))
            elif name == "production_sites" and not own_page:
                out.append(item(name, PLANT, PLANT_QUOTE, asked.source_id))
            else:
                out.append(not_found(name))
        return out

    with caplog.at_level(logging.INFO, logger="app.extraction.stage"):
        run_stage(engine, organisation_id, run_id, scripted(respond))

    facts = facts_of(engine, run_id)
    assert facts["legal_form"].status == "proposed" and facts["legal_form"].value == "SAS"
    assert facts["legal_form"].source_id == own and facts["legal_form"].group_level is None
    sites = facts["production_sites"]
    assert sites.status == "proposed" and sites.group_level == SISTER
    assert run_row(engine, run_id).grounding_failures == 1
    assert "other_group_entity=1" in caplog.text and "not_named_near_quote=0" in caplog.text
    # Counts only: neither the quote nor a name is logged.
    assert "GmbH" not in caplog.text and "BERICAP" not in caplog.text


def test_without_another_source_the_legal_form_reads_no_public_evidence(engine: Engine) -> None:
    organisation_id, run_id, _press = setup(
        engine, PAGE, PRESS, legal_name=ENTITY, website=WEBSITE, country="FR", group_name=GROUP
    )

    def respond(asked: Asked) -> list[dict[str, Any]]:
        return [
            item(name, "GmbH & Co. KG", SISTER, asked.source_id)
            if name == "legal_form"
            else not_found(name)
            for name in asked.fields
        ]

    run_stage(engine, organisation_id, run_id, scripted(respond))

    fact = facts_of(engine, run_id)["legal_form"]
    assert fact.status == "not_found" and fact.value is None and fact.group_level is None


# --- other facts from that passage are labelled with that entity ---


def test_another_fact_of_the_passage_is_labelled_with_the_entity_as_printed() -> None:
    kept, tally = plant()

    assert kept is not None and kept.group_level == SISTER and kept.value == PLANT
    assert tally.grounding_failures == 0


def test_the_parent_group_with_its_legal_form_is_labelled_with_the_group_name() -> None:
    text = "Results of the year.\nBERICAP HOLDING GMBH reports that the group employs 4000 people."

    kept, _tally = judged("employee_count", "4000", "the group employs 4000 people", text=text)

    assert kept is not None and kept.group_level == GROUP


def test_the_parent_groups_legal_form_is_not_the_entitys() -> None:
    text = "BERICAP Holding GmbH is registered in Budenheim under HRB 1234."

    kept, tally = legal_form(quote="BERICAP Holding GmbH is registered", value="GmbH", text=text)

    assert kept is None and tally.other_group_entity == 1


def test_a_passage_naming_the_entity_and_the_group_labels_a_quote_naming_neither() -> None:
    # The page of #195 that names the entity: its quote's passage also names "Amcor plc".
    entity, group = "Amcor Flexibles Sarrebourg SAS", "Amcor plc"
    text = f"{entity} is part of {group}. Amcor employs 41000 people worldwide."
    supplier = Supplier(entity, None, "FR", group_name=group)

    kept, _tally = judged(
        "employee_count", "41000", "Amcor employs 41000 people worldwide", text, supplier
    )

    assert kept is not None and kept.group_level == group


# --- unchanged where nothing tells the entities apart ---


def test_a_supplier_without_a_parent_group_is_unchanged() -> None:
    alone = Supplier(ENTITY, WEBSITE, "FR")

    kept, tally = legal_form(supplier=alone)

    assert kept is not None and kept.value == "GmbH & Co. KG" and kept.group_level is None
    assert tally.grounding_failures == 0


def test_a_natural_person_is_unchanged() -> None:
    person = Supplier("Jean Dupont", None, "FR", natural_person=True, group_name=GROUP)
    text = "Local trades.\nBERICAP GmbH & Co. KG supplies the workshop of Lyon with caps."

    kept, _tally = legal_form(quote=SISTER, text=text, supplier=person)

    assert kept is not None and kept.group_level is None


def test_a_bare_name_without_a_legal_form_is_unchanged() -> None:
    text = "Closures news.\nBERICAP opened a plant in Kunshan, China last spring."

    kept, _tally = plant(quote="BERICAP opened a plant in Kunshan, China", text=text)

    # The page names the entity: no label, as in #195.
    assert kept is not None and kept.group_level is None


@pytest.mark.parametrize("printed", ["Acme SAS", "Acme S.A.S.", "ACME sas"])
def test_the_confirmed_entitys_own_name_and_legal_form_is_unchanged(printed: str) -> None:
    acme = Supplier("Acme SAS", None, "FR", group_name="Acme Group plc")
    text = f"{printed} is a French company. It employs 250 people in Lyon."

    # The value as printed: the guard on words (`value_supported`) needs a word of the quote.
    form, _tally = legal_form(
        quote=f"{printed} is a French company", value=printed, text=text, supplier=acme
    )
    staff, _tally = judged("employee_count", "250", "It employs 250 people", text, acme)

    assert form is not None and form.value == printed and form.group_level is None
    assert staff is not None and staff.group_level is None


@pytest.mark.parametrize(
    ("printed", "country"),
    [
        ("BERICAP SA", "FR"),  # SA: not in the table (used in many countries)
        ("BERICAP SAS", "FR"),  # SAS: also used in France
        ("BERICAP Ltd", "IE"),  # Ltd: used in Ireland
        ("BERICAP GmbH", None),  # no country: no conclusion
        ("BERICAP Pty Ltd", "FR"),  # Pty: not in the table
    ],
)
def test_a_legal_form_with_no_conclusion_is_unchanged(printed: str, country: str | None) -> None:
    supplier = Supplier(ENTITY, WEBSITE, country, group_name=GROUP)
    text = f"News.\n{printed} has opened a new production plant in Kunshan, China."

    form, _t = legal_form(
        quote=f"{printed} has opened", value=printed, text=text, supplier=supplier
    )
    site, _t = plant(text=text, supplier=supplier)

    assert form is not None and form.group_level is None
    assert site is not None and site.group_level is None


def test_a_company_whose_name_only_starts_like_the_suppliers_is_unchanged() -> None:
    text = "News.\nBERICAP and Bericapital Ltd: Bericapital Ltd has opened an office in Kunshan."

    kept, _tally = judged(
        "production_sites", "Kunshan", "Bericapital Ltd has opened an office in Kunshan", text
    )

    assert kept is not None and kept.group_level is None


def test_a_name_followed_by_connectors_only_is_no_company() -> None:
    assert named_companies("BERICAP and Amcor agreed", ["bericap"]) == []
    assert named_companies("BERICAP & Amcor agreed", ["bericap"]) == []
    assert named_companies("BERICAP as a leader of closures", ["bericap"]) == []
    assert named_companies("BERICAP se développe", ["bericap"]) == []


def test_named_companies_read_the_legal_form_whatever_its_case_and_points() -> None:
    (one,) = named_companies(normalise("(BERICAP GMBH & CO KG) opened"), ["bericap"])
    (two,) = named_companies(normalise("Acme, S. A. S. and more"), ["acme"])
    (three,) = named_companies(normalise("made by BERICAP Ltd."), ["bericap"])

    assert one.forms == ("gmbh", "kg") and one.printed == "BERICAP GMBH & CO KG"
    assert two.forms == ("sas",)
    assert three.printed == "BERICAP Ltd"


def test_a_form_with_a_conclusion_needs_every_printed_form_in_the_table() -> None:
    rules = group_entities(ENTITY, GROUP, "FR")
    (company,) = named_companies(SISTER, ["bericap"])

    assert rules.is_other(company)
    assert not group_entities(ENTITY, GROUP, "DE").is_other(company)


# --- every source, and passages covering several entities ---


def test_the_suppliers_own_website_shared_with_the_group_follows_the_rule() -> None:
    text = (
        "Legal notice.\n"
        f"This website is published by {SISTER}, Kirchstrasse 5, 55257 Budenheim, Germany."
    )
    url = f"{WEBSITE}/legal-notice"

    form, tally = legal_form(
        quote=f"published by {SISTER}", text=text, url=url, source_type="supplier_claim"
    )
    site, _t = judged(
        "production_sites",
        "Budenheim, Germany",
        "Kirchstrasse 5, 55257 Budenheim, Germany",
        text,
        url=url,
        source_type="supplier_claim",
    )

    assert form is None and tally.other_group_entity == 1
    assert site is not None and site.group_level == SISTER
    assert site.source.source_type == "supplier_claim"


def test_the_groups_own_website_follows_the_rule() -> None:
    group_site = "https://www.bericap-group.example"
    supplier = Supplier(ENTITY, WEBSITE, "FR", group_name=GROUP, group_website=group_site)
    text = f"Our plants.\n{SISTER} has opened a new production plant in Kunshan, China."

    form, _t = legal_form(text=text, supplier=supplier, url=f"{group_site}/plants")
    site, _t = plant(text=text, supplier=supplier, url=f"{group_site}/plants")

    assert form is None
    assert site is not None and site.group_level == SISTER
    assert site.source.source_type == "supplier_claim"  # the group's own claim


GLEIF = "https://search.gleif.org/#/record/969500EAKWZ863LPRM81"
GLEIF_TEXT = "\n".join(
    [
        "Legal name: BERICAP",
        "LEI: 969500EAKWZ863LPRM81",
        "Legal form: SAS",
        "Legal address: 21600 Longvic, FR",
        "Ultimate parent: BERICAP Holding GmbH (Budenheim, DE), LEI 5299000000000000BH01",
        "Group entities registered with an LEI: 3 in 2 countries",
        "BERICAP Holding GmbH, Budenheim, DE",
        "BERICAP, Longvic, FR",
        "BERICAP GmbH & Co. KG, Budenheim, DE",
    ]
)


def test_the_gleif_legal_form_line_of_the_entity_is_kept_unlabelled() -> None:
    kept, _tally = legal_form(quote="Legal form: SAS", value="SAS", text=GLEIF_TEXT, url=GLEIF)

    assert kept is not None and kept.value == "SAS" and kept.group_level is None


def test_a_value_from_a_listed_group_entitys_gleif_line_follows_the_rule() -> None:
    form, tally = legal_form(quote="BERICAP GmbH & Co. KG, Budenheim", text=GLEIF_TEXT, url=GLEIF)
    site, _t = judged(
        "production_sites",
        "Budenheim, DE",
        "BERICAP GmbH & Co. KG, Budenheim, DE",
        GLEIF_TEXT,
        url=GLEIF,
    )

    assert form is None and tally.other_group_entity == 1
    assert site is not None and site.group_level == SISTER


ACME = Supplier("Acme SAS", None, "FR", group_name="Acme Group plc")
BOTH = (
    "Acme SAS makes valves in Lyon with 250 staff, while its sister Acme GmbH runs a plant in "
    "Stuttgart with 900 staff."
)


def test_a_quote_naming_the_other_entity_follows_the_rule() -> None:
    kept, _t = judged(
        "production_sites", "Stuttgart", "Acme GmbH runs a plant in Stuttgart", BOTH, ACME
    )

    assert kept is not None and kept.group_level == "Acme GmbH"


def test_a_quote_naming_the_confirmed_entity_and_no_other_is_the_entitys() -> None:
    form, _t = judged("legal_form", "SAS", "Acme SAS makes valves in Lyon", BOTH, ACME)
    site, _t = judged("production_sites", "Lyon", "Acme SAS makes valves in Lyon", BOTH, ACME)

    assert form is not None and form.group_level is None
    assert site is not None and site.group_level is None


def test_a_quote_naming_neither_takes_the_first_other_entity_of_the_passage() -> None:
    text = (
        "Acme SAS is the French arm; Acme GmbH and Acme BV are its sisters. The plants employ "
        "1150 staff."
    )

    kept, _t = judged("employee_count", "1150", "The plants employ 1150 staff", text, ACME)

    assert kept is not None and kept.group_level == "Acme GmbH"


def test_the_label_is_at_most_300_characters() -> None:
    long_name = "Acme " + "Very " * 70 + "SAS"
    supplier = Supplier(long_name, None, "FR", group_name="Acme Group plc")
    printed = "Acme " + "Very " * 70 + "GmbH"

    rules = group_entities(supplier.name, "Acme Group plc", "FR")
    label = rules.other_entity("x", [f"{printed} owns x"])

    assert label is not None and len(label) <= 300
