"""#202: a fact from a third-party page must name the supplier near its quote.

Replays the Bericap / New York Power Authority case (dev, 16 Nov 2026): a press release listing
several companies, the supplier named in one paragraph and the quote in another."""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from app.extraction.grounding import fold, passages
from app.extraction.settings import ExtractionSettings
from app.extraction.stage import SourceText, Supplier, make_extraction_stage
from tests.extraction.support import (
    DEFINITION,
    PROMPTS,
    Asked,
    add_source,
    context_for,
    facts_of,
    item,
    not_found,
    providers_with,
    run_row,
    scripted,
)
from tests.extraction.test_stage import run_stage, setup

SUPPLIER = "Bericap GmbH & Co. KG"
WEBSITE = "https://www.bericap.com"
PRESS = "https://www.nypa.example/news/press-releases/2026-allocations"
QUOTE = "more than $22 million project to build a 100,000-square-foot facility in Cheektowaga"
VALUE = "100,000-square-foot facility in Cheektowaga"
OTHER = (
    f"Westwood Foods plans a {QUOTE}, creating 85 jobs over the next five years, according to "
    "the application filed with the Authority."
)
PRESS_RELEASE = "\n".join(
    [
        "The New York Power Authority Board approved low-cost power allocations for several "
        "companies across Western New York on Tuesday.",
        "Bericap North America, a maker of plastic closures, will receive 500 kilowatts for its "
        "plant in Erie County.",
        OTHER,
        "The allocations support more than 1,200 jobs across the region.",
    ]
)


def sites(quote: str = QUOTE, value: str = VALUE) -> Any:
    def respond(asked: Asked) -> list[dict[str, Any]]:
        return [
            item(name, value, quote, asked.source_id)
            if name == "production_sites"
            else not_found(name)
            for name in asked.fields
        ]

    return respond


def production_site(engine: Engine, text: str, url: str = PRESS, **identity: Any) -> Any:
    values = {"legal_name": SUPPLIER, "website": WEBSITE, **identity}
    organisation_id, run_id, _source = setup(engine, text, url, **values)
    run_stage(engine, organisation_id, run_id, scripted(sites()))
    return facts_of(engine, run_id)["production_sites"], run_row(engine, run_id)


def test_the_bericap_case_a_quote_in_another_companys_paragraph_is_dropped(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.extraction.stage"):
        fact, run = production_site(engine, PRESS_RELEASE)

    assert fact.status == "not_found"
    assert run.grounding_failures == 1
    assert "not_named_near_quote=1" in caplog.text
    # Counts only: neither the quote nor the supplier's name is logged.
    assert "Cheektowaga" not in caplog.text and "Bericap" not in caplog.text


def test_the_same_quote_next_to_the_suppliers_name_is_kept(engine: Engine) -> None:
    text = PRESS_RELEASE.replace("Westwood Foods", "Bericap North America")

    fact, run = production_site(engine, text)

    assert fact.status == "proposed" and fact.quote == QUOTE
    assert fact.source_type == "third_party"
    assert run.grounding_failures == 0


def test_the_website_label_near_the_quote_is_enough(engine: Engine) -> None:
    text = PRESS_RELEASE.replace("Westwood Foods", "The bericap.com subsidiary")

    fact, _run = production_site(engine, text)

    assert fact.status == "proposed"


def test_a_long_paragraph_counts_only_the_characters_near_the_quote(engine: Engine) -> None:
    filler = "The region has seen steady growth in manufacturing. " * 20  # about 1000 characters
    text = f"Bericap North America is one of the companies. {filler}Westwood Foods plans a {QUOTE}."

    far, _run = production_site(engine, text)
    near, _run = production_site(engine, text.replace("Westwood Foods", "Bericap North America"))

    assert far.status == "not_found" and near.status == "proposed"


def test_the_distance_is_a_setting(engine: Engine) -> None:
    filler = "The region has seen steady growth in manufacturing. " * 20
    text = f"Bericap North America is one of the companies. {filler}Westwood Foods plans a {QUOTE}."
    organisation_id, run_id, _source = setup(
        engine, text, PRESS, legal_name=SUPPLIER, website=WEBSITE
    )
    context = context_for(engine, organisation_id, run_id, providers_with(scripted(sites())))

    make_extraction_stage(
        DEFINITION, PROMPTS, ExtractionSettings(groups_per_call=1, passage_chars=2000)
    )(context)

    assert facts_of(engine, run_id)["production_sites"].status == "proposed"


def test_an_own_website_fact_without_the_name_nearby_is_kept(engine: Engine) -> None:
    fact, run = production_site(engine, PRESS_RELEASE, url=f"{WEBSITE}/news/expansion")

    assert fact.status == "proposed" and fact.source_type == "supplier_claim"
    assert run.grounding_failures == 0


def test_a_registry_domain_fact_without_the_name_nearby_is_kept(engine: Engine) -> None:
    fact, _run = production_site(
        engine,
        PRESS_RELEASE,
        url="https://registry.example/record/1",
        registry_ids={"website": "https://registry.example"},
    )

    assert fact.status == "proposed" and fact.source_type == "supplier_claim"


def test_the_gleif_record_keeps_todays_rule(engine: Engine) -> None:
    fact, _run = production_site(engine, PRESS_RELEASE, url="https://search.gleif.org/#/record/X")

    assert fact.status == "proposed" and fact.source_type == "third_party"


GROUP = "Amcor plc"
ENTITY = "Amcor Flexibles Sarrebourg SAS"
GROUP_QUOTE = "Amcor employs 41000 people worldwide"


def employees(engine: Engine, text: str, url: str = PRESS, **identity: Any) -> Any:
    organisation_id, run_id, _source = setup(
        engine, text, url, legal_name=ENTITY, website=None, group_name=GROUP, **identity
    )

    def respond(asked: Asked) -> list[dict[str, Any]]:
        return [
            item(name, "41000", GROUP_QUOTE, asked.source_id)
            if name == "employee_count"
            else not_found(name)
            for name in asked.fields
        ]

    run_stage(engine, organisation_id, run_id, scripted(respond))
    return facts_of(engine, run_id)["employee_count"]


def test_a_group_level_fact_with_the_group_named_nearby_is_kept_and_labelled(
    engine: Engine,
) -> None:
    text = "Packaging news of the week.\nAmcor plc is a global packaging company. " + GROUP_QUOTE

    fact = employees(engine, text)

    assert fact.status == "proposed" and fact.group_level == GROUP


def test_a_group_name_inside_the_quote_counts(engine: Engine) -> None:
    text = "Amcor plc is a global packaging company.\nBorel says that " + GROUP_QUOTE + "."

    assert employees(engine, text).status == "proposed"


def test_a_group_level_fact_with_the_group_named_in_another_paragraph_is_dropped(
    engine: Engine,
) -> None:
    other = "Amcor plc is a global packaging company.\nBorel employs 41000 people worldwide."
    organisation_id, run_id, _source = setup(
        engine, other, PRESS, legal_name=ENTITY, website=None, group_name=GROUP
    )

    def respond(asked: Asked) -> list[dict[str, Any]]:
        return [
            item(name, "41000", "employs 41000 people worldwide", asked.source_id)
            if name == "employee_count"
            else not_found(name)
            for name in asked.fields
        ]

    run_stage(engine, organisation_id, run_id, scripted(respond))
    assert facts_of(engine, run_id)["employee_count"].status == "not_found"


def test_the_groups_own_website_keeps_todays_rule(engine: Engine) -> None:
    text = "News.\nThe group employs 41000 people worldwide."
    organisation_id, run_id, _source = setup(
        engine,
        text,
        "https://www.amcor.com/news",
        legal_name=ENTITY,
        website=None,
        group_name=GROUP,
        group_website="https://www.amcor.com",
    )

    def respond(asked: Asked) -> list[dict[str, Any]]:
        return [
            item(name, "41000", "The group employs 41000 people worldwide", asked.source_id)
            if name == "employee_count"
            else not_found(name)
            for name in asked.fields
        ]

    run_stage(engine, organisation_id, run_id, scripted(respond))

    fact = facts_of(engine, run_id)["employee_count"]
    assert fact.status == "proposed" and fact.source_type == "supplier_claim"
    assert fact.group_level == GROUP


def test_a_natural_person_keeps_todays_rule(engine: Engine) -> None:
    text = "Local trades.\n[…]\nOther news.\nThe workshop employs 3 people in Lyon."
    organisation_id, run_id, _source = setup(
        engine, text, PRESS, legal_name="Jean Dupont", website=None, natural_person=True
    )

    def respond(asked: Asked) -> list[dict[str, Any]]:
        return [
            item(name, "3", "The workshop employs 3 people in Lyon", asked.source_id)
            if name == "employee_count"
            else not_found(name)
            for name in asked.fields
        ]

    run_stage(engine, organisation_id, run_id, scripted(respond))

    assert facts_of(engine, run_id)["employee_count"].status == "proposed"


def test_a_pdf_paragraph_spans_its_layout_lines(engine: Engine) -> None:
    text = (
        "Annual review of the region.\n\n"
        "Bericap North America, a maker of plastic closures, plans a\n"
        f"{QUOTE}.\n\n"
        "Other companies also invested."
    )
    organisation_id, run_id, _source = setup(
        engine, "placeholder", "https://other.example/a", legal_name=SUPPLIER, website=WEBSITE
    )
    with_pdf = add_source(
        engine,
        organisation_id,
        run_id,
        "https://region.example/review.pdf",
        text,
        content_type="application/pdf",
    )
    run_stage(engine, organisation_id, run_id, scripted(sites()))

    fact = facts_of(engine, run_id)["production_sites"]
    assert fact.status == "proposed" and fact.source_id == with_pdf


# --- the passage itself ---


def test_passages_stop_at_the_paragraph() -> None:
    text = "Bericap is named here.\nWestwood Foods plans a new plant in Cheektowaga."

    (passage,) = passages(text, "a new plant in Cheektowaga", 600)

    assert passage == fold("Westwood Foods plans a new plant in Cheektowaga.")


def test_passages_stop_at_the_distance_within_a_paragraph() -> None:
    text = "Bericap " + "x" * 100 + " a new plant in Cheektowaga " + "y" * 100 + " Bericap"

    (passage,) = passages(text, "a new plant in Cheektowaga", 50)

    assert "bericap" not in passage and "cheektowaga" in passage
    assert len(passage) == 50 + len("a new plant in Cheektowaga") + 50


def test_passages_cover_a_quote_across_lines_and_every_place_of_the_quote() -> None:
    text = "Westwood: a new plant\nin Cheektowaga.\nBericap: a new plant in Cheektowaga."

    found = passages(text, "a new plant in Cheektowaga", 600)

    assert found == [fold("Westwood: a new plant in Cheektowaga."), fold(text.split("\n")[2])]


def test_passages_of_a_quote_not_in_the_text_are_empty() -> None:
    assert passages("Bericap makes closures.", "a new plant", 600) == []
    assert passages("", "a new plant", 600) == []


def test_a_name_cut_by_the_edge_of_the_passage_is_not_matched() -> None:
    text = "Bericap " + "x" * 46 + " a new plant in Cheektowaga"
    source = SourceText(
        id=uuid4(),
        url=PRESS,
        fetched_at=datetime.now(UTC),
        author=None,
        text=text,
        source_type="third_party",
        publisher="nypa.example",
        normalised=text,
        folded=fold(text),
    )
    supplier = Supplier(SUPPLIER, WEBSITE, "US")

    assert supplier.needs_passage(source)
    assert not supplier.named_near(source, "a new plant in Cheektowaga", 50)
    assert supplier.named_near(source, "a new plant in Cheektowaga", 60)
