"""#195: a group entity uses its parent group's public evidence, labelled "Group level"."""

from typing import Any

import pytest
from sqlalchemy import Engine

from app.collection.retrieval import IdentityRecord, _supplier_text
from app.extraction.grounding import group_names, names_group
from tests.extraction.support import Asked, facts_of, item, not_found, scripted
from tests.extraction.test_stage import run_stage, setup

ENTITY = "Amcor Flexibles Sarrebourg SAS"
GROUP = "Amcor plc"
ENTITY_PAGE = "Amcor Flexibles Sarrebourg SAS employs 400 people in Sarrebourg."
GROUP_PAGE = "Amcor plc is a global packaging company. Amcor employs 41000 people worldwide."
OTHER_PAGE = "Amcorp Rentals makes pallets and employs 12 people."
GROUP_QUOTE = "Amcor employs 41000 people worldwide"
BASE = "https://www.news.example"


def respond_with(quote: str) -> Any:
    def respond(asked: Asked) -> list[dict[str, Any]]:
        return [
            item(name, "41000", quote, asked.source_id)
            if name == "employee_count"
            else not_found(name)
            for name in asked.fields
        ]

    return respond


def employees(engine: Engine, text: str, quote: str, **identity: Any) -> Any:
    organisation_id, run_id, _source = setup(
        engine, text, f"{BASE}/a", legal_name=ENTITY, website=None, **identity
    )
    run_stage(engine, organisation_id, run_id, scripted(respond_with(quote)))
    return facts_of(engine, run_id)["employee_count"]


def test_the_amcor_case_a_group_page_is_kept_and_labelled(engine: Engine) -> None:
    fact = employees(engine, GROUP_PAGE, GROUP_QUOTE, group_name=GROUP)

    assert fact.status == "proposed" and fact.group_level == GROUP
    assert fact.quote == GROUP_QUOTE


def test_a_page_naming_the_entity_has_no_label_even_when_it_names_the_group(
    engine: Engine,
) -> None:
    # The group by its name alone: with its legal form ("Amcor plc") in the quote's passage, the
    # fact is about the parent group (#209, test_other_entity.py).
    text = f"{ENTITY} is part of the Amcor group. Amcor employs 41000 people worldwide."
    fact = employees(engine, text, GROUP_QUOTE, group_name=GROUP)

    assert fact.status == "proposed" and fact.group_level is None


def test_without_a_parent_group_the_group_page_is_not_used(engine: Engine) -> None:
    fact = employees(engine, GROUP_PAGE, GROUP_QUOTE)

    assert fact.status == "not_found" and fact.group_level is None


def test_a_page_naming_another_company_with_the_same_first_word_is_not_accepted(
    engine: Engine,
) -> None:
    fact = employees(
        engine, OTHER_PAGE, "Amcorp Rentals makes pallets and employs 12 people", group_name=GROUP
    )

    assert fact.status == "not_found"


def test_a_group_quote_must_still_be_verbatim_in_the_text(engine: Engine) -> None:
    fact = employees(engine, GROUP_PAGE, "Amcor employs 99000 people worldwide", group_name=GROUP)

    assert fact.status == "not_found"


def test_the_groups_own_website_is_the_groups_claim(engine: Engine) -> None:
    organisation_id, run_id, _source = setup(
        engine,
        "The group employs 41000 people worldwide.",
        "https://www.amcor.com/about",
        legal_name=ENTITY,
        website=None,
        group_name=GROUP,
        group_website="https://www.amcor.com",
    )
    run_stage(
        engine,
        organisation_id,
        run_id,
        scripted(respond_with("The group employs 41000 people worldwide")),
    )

    fact = facts_of(engine, run_id)["employee_count"]
    assert fact.status == "proposed" and fact.group_level == GROUP
    assert fact.source_type == "supplier_claim"


def test_group_names_keep_group_words_and_match_whole_words() -> None:
    assert group_names("Mondi Group plc") == ["mondi group plc", "mondi group"]
    assert names_group("about mondi group results", group_names("Mondi Group plc"), None)
    assert not names_group("about mondi foods results", group_names("Mondi Group plc"), None)
    assert not names_group("about amcorp", group_names("Amcor plc"), None)


def test_the_retrieval_query_names_entity_and_group_both_quoted() -> None:
    text = _supplier_text(IdentityRecord(ENTITY, None, "FR", GROUP, "https://www.amcor.com"), [])

    assert f'Legal name: "{ENTITY}"' in text and f'Parent group: "{GROUP}"' in text
    assert "Group website: https://www.amcor.com" in text
    assert "about the supplier entity itself and about its group" in text


def test_the_retrieval_query_is_unchanged_without_a_group() -> None:
    text = _supplier_text(IdentityRecord(ENTITY, None, "FR"), [])

    assert "Parent group" not in text


@pytest.mark.parametrize("with_group", [True, False])
def test_the_extraction_supplier_line_names_the_group(with_group: bool) -> None:
    from app.extraction.stage import Supplier

    line = Supplier(ENTITY, None, "FR", group_name=GROUP if with_group else None).text()

    assert (f'Parent group: "{GROUP}"' in line) is with_group


def test_the_group_name_is_kept_with_the_company_names_of_redaction(engine: Engine) -> None:
    from sqlalchemy.orm import Session

    from app.collection.source_store import identity_redaction

    _org, run_id, _source = setup(
        engine, GROUP_PAGE, f"{BASE}/a", legal_name=ENTITY, group_name=GROUP
    )

    with Session(engine) as db:
        assert identity_redaction(db, run_id).company_names == (ENTITY, GROUP)


def test_a_page_naming_a_company_that_shares_the_groups_name_is_accepted_as_group_level(
    engine: Engine,
) -> None:
    text = "Amcor Foods employs 41000 people in Europe."
    fact = employees(engine, text, "Amcor Foods employs 41000 people", group_name=GROUP)

    assert fact.status == "proposed" and fact.group_level == GROUP
