"""A source id reaches the model intact (#130).

The flaky extraction tests had one cause: the phone-number rule of the redaction gate took a run of
digit groups inside some random source ids (`…-0580-4975-…`) for a dashed phone number and replaced
it with `[…]`. The model (here the fake) then saw, and gave back, an id that is not the source's,
and the grounding check discarded every value of that source. About 1 random id in 600 has such a
run, so the tests failed now and then whatever the machine. These tests fix the ids instead of
drawing them, so they fail on every run while the cause is there.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import Engine

from tests.extraction.support import (
    FACT_FIELDS,
    SITE,
    Asked,
    add_source,
    context_for,
    facts_of,
    item,
    not_found,
    providers_with,
    run_row,
    scripted,
    set_identity,
    stage,
)
from tests.factories import create_organisation
from tests.runs_support import create_run

ABOUT = (
    "Acme Supplies SA was founded in 2005 in Lyon. It employs 250 people. "
    "We are certified ISO 9001."
)
# Random version-4 ids drawn once, each with a digit run the phone rule took for a number.
PHONE_LIKE_IDS = [
    uuid.UUID("6a8ac4ba-0580-4975-ad2f-89d94a2f20aa"),
    uuid.UUID("03923845-0264-4491-a2a9-908ceebb6118"),
    uuid.UUID("f3ace47a-3a78-4cac-b6dc-081755611568"),
    uuid.UUID("529f2ba3-2a1a-4960-9931-bf0735a30cee"),
]
FOUND = {
    "founding_year": ("2005", "was founded in 2005 in Lyon"),
    "employee_count": ("250", "It employs 250 people"),
    "quality_management": ("ISO 9001", "We are certified ISO 9001"),
}


def answer(asked: Asked) -> list[dict[str, Any]]:
    """What a model answers: the id it was given, and the values of the page."""
    return [
        item(name, *FOUND[name], asked.source_id) if name in FOUND else not_found(name)
        for name in asked.fields
    ]


def setup(engine: Engine, source_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, stage="extraction", enqueue=False)
    set_identity(engine, run_id, website=SITE)
    add_source(engine, organisation_id, run_id, f"{SITE}/about", ABOUT, source_id=source_id)
    return organisation_id, run_id


@pytest.mark.parametrize("concurrency", [1, 8])
@pytest.mark.parametrize("source_id", PHONE_LIKE_IDS, ids=str)
def test_a_source_id_with_a_phone_like_digit_run_is_sent_intact_and_its_values_kept(
    engine: Engine, source_id: uuid.UUID, concurrency: int
) -> None:
    organisation_id, run_id = setup(engine, source_id)
    adapter = scripted(answer)

    context = context_for(engine, organisation_id, run_id, providers_with(adapter))
    stage(extract_concurrency=concurrency)(context)

    assert adapter.asked
    assert {asked.source_id for asked in adapter.asked} == {str(source_id)}
    facts = facts_of(engine, run_id)
    assert sorted(facts) == sorted(FACT_FIELDS)
    for name, (value, quote) in FOUND.items():
        fact = facts[name]
        assert (fact.status, fact.value, fact.quote, fact.source_id) == (
            "proposed",
            value,
            quote,
            source_id,
        ), name
    row = run_row(engine, run_id)
    assert (row.grounding_failures, row.invalid_items) == (0, 0)
