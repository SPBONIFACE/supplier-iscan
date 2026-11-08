"""#134: output-structure fragments in a statement, a gap or a fact value make the item invalid."""

import pytest
from pydantic import ValidationError

from app.assessment.rules import to_statement
from app.llm_schemas import FieldExtraction, RawAssessmentStatement, leaks_structure

LEAK = (
    "Environmental certification documents for the supplier's plants, issued by a recognised "
    "certification body.','cites_buyer_context':false}]}Ī{"
)


def test_the_exact_leaked_string_is_detected() -> None:
    assert leaks_structure(LEAK)
    assert leaks_structure("see cited_fact_ids")
    assert leaks_structure("x}]")
    assert not leaks_structure("ISO 9001 [1], certified. Revenue: EUR 4.2m (2025).")
    assert not leaks_structure('The "Quality" and "Safety" policies')
    assert not leaks_structure(None)


@pytest.mark.parametrize("kind", ["evidence_gap", "strength", "fit"])
def test_a_leaked_fragment_in_text_or_gap_evidence_makes_the_statement_invalid(kind: str) -> None:
    in_gap = RawAssessmentStatement(kind=kind, text="Missing certificate.", gap_evidence=LEAK)
    in_text = RawAssessmentStatement(kind=kind, text=LEAK, cited_fact_ids=["f"])

    assert to_statement(in_gap) is None
    assert to_statement(in_text) is None


def test_a_clean_gap_statement_is_still_valid() -> None:
    clean = RawAssessmentStatement(
        kind="evidence_gap", text="Missing certificate.", gap_evidence="ISO 14001 certificates."
    )

    assert to_statement(clean) is not None


def test_a_leaked_fragment_in_an_extracted_value_is_invalid() -> None:
    with pytest.raises(ValidationError):
        FieldExtraction(field="f", status="found", value=LEAK, quote="quote", source_id="1")

    kept = FieldExtraction(
        field="f", status="found", value="ISO 9001 [1]", quote="quote", source_id="1"
    )
    assert kept.value == "ISO 9001 [1]"
