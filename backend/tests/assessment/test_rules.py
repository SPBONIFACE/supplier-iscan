"""The validation rules of the assessment draft (#25): what is rejected and counted, what the code
adds. Pure functions, no database, no provider."""

from typing import Any

from app.assessment.rules import (
    ASSUMPTION,
    BuyerContext,
    FactView,
    Tally,
    to_statement,
    validate,
    with_assumption,
)
from app.llm_schemas import (
    ASSESSMENT_KINDS,
    RECOMMENDATION_KINDS,
    AssessmentStatement,
    RawAssessmentStatement,
)

FOUND = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
MISSING = "00000000-0000-4000-8000-000000000003"
PERSON = "00000000-0000-4000-8000-000000000004"
STRANGER = "00000000-0000-4000-8000-0000000000ff"

FACTS = {
    FOUND: FactView(FOUND, "quality_management", "proposed", "ISO 9001", "certified ISO 9001"),
    OTHER: FactView(OTHER, "production_sites", "approved", "Leeds", "our plant in Leeds"),
    MISSING: FactView(MISSING, "employee_count", "not_found", None, None),
    PERSON: FactView(PERSON, "management_team", "proposed", "Jo", "led by Jo", True),
}


def statement(kind: str = "strength", **values: Any) -> AssessmentStatement:
    values.setdefault("text", "A statement.")
    values.setdefault("cited_fact_ids", [] if kind == "evidence_gap" else [FOUND])
    return AssessmentStatement.model_validate({"kind": kind, **values})


def run(
    statements: list[AssessmentStatement],
    kinds: tuple[str, ...] = ASSESSMENT_KINDS,
    context: BuyerContext | None = None,
    language: str = "en",
) -> tuple[list[str], Tally]:
    tally = Tally()
    kept = validate(statements, kinds, FACTS, context, language, tally)
    return [item.text for item in kept], tally


def rejected(item: AssessmentStatement, **kwargs: Any) -> bool:
    texts, tally = run([item], **kwargs)
    return not texts and tally.rejected == 1


def test_a_statement_with_a_valid_fact_is_kept() -> None:
    texts, tally = run([statement(cited_fact_ids=[FOUND.upper(), OTHER])])
    assert texts == ["A statement."] and tally.rejected == 0


def test_a_statement_citing_no_fact_is_rejected_and_counted() -> None:
    assert rejected(statement(cited_fact_ids=[]))


def test_a_fact_that_is_not_in_this_run_is_rejected() -> None:
    assert rejected(statement(cited_fact_ids=[FOUND, STRANGER]))


def test_a_not_found_fact_is_rejected() -> None:
    assert rejected(statement(cited_fact_ids=[MISSING]))


def test_a_fact_of_a_people_field_is_rejected_whatever_the_wording() -> None:
    assert rejected(statement("weakness", cited_fact_ids=[PERSON]))
    assert rejected(statement("threat", cited_fact_ids=[FOUND, PERSON]))


def test_a_level_without_cited_facts_is_rejected() -> None:
    gap = statement("evidence_gap", level="high", gap_evidence="A certificate.")
    assert rejected(gap)
    assert not rejected(statement("risk_indicator", level="low"))


def test_an_evidence_gap_names_the_missing_evidence_and_needs_no_fact() -> None:
    assert not rejected(statement("evidence_gap", gap_evidence="An ISO 14001 certificate."))
    assert rejected(statement("evidence_gap", gap_evidence="  "))
    assert rejected(statement("evidence_gap"))
    assert rejected(statement("strength", gap_evidence="Something."))


def test_a_gap_may_cite_a_found_fact_but_not_a_not_found_one() -> None:
    assert not rejected(statement("evidence_gap", cited_fact_ids=[FOUND], gap_evidence="More."))
    assert rejected(statement("evidence_gap", cited_fact_ids=[MISSING], gap_evidence="More."))


def test_a_financial_stability_gap_is_dropped_in_both_languages() -> None:
    for text, evidence in (
        ("No public evidence on financial stability.", "Audited accounts."),
        ("Pas de preuve publique.", "Le dernier bilan et le chiffre d'affaires."),
        ("No evidence found.", "The latest turnover and credit information."),
    ):
        assert rejected(statement("evidence_gap", text=text, gap_evidence=evidence))
    assert not rejected(statement("evidence_gap", gap_evidence="An ISO 14001 certificate."))


def test_label_timing_and_level_rules_of_the_recommendations() -> None:
    kinds = RECOMMENDATION_KINDS
    assert rejected(statement("relationship_level"), kinds=kinds)
    assert not rejected(statement("relationship_level", label="preferred"), kinds=kinds)
    assert rejected(statement("volume_share", label="strategic"), kinds=kinds)
    assert rejected(statement("next_action"), kinds=kinds)
    assert not rejected(statement("next_action", timing="within 2 weeks"), kinds=kinds)
    assert rejected(statement("volume_share", timing="soon"), kinds=kinds)
    assert rejected(statement("procurement_priority"), kinds=kinds)
    assert not rejected(statement("procurement_priority", level="medium"), kinds=kinds)


def test_the_label_must_be_one_of_the_three() -> None:
    raw = RawAssessmentStatement(kind="relationship_level", text="x", label="best")
    assert to_statement(raw) is None


def test_each_recommendation_kind_but_next_action_is_kept_once() -> None:
    kinds = RECOMMENDATION_KINDS
    texts, tally = run(
        [
            statement("volume_share", text="first"),
            statement("volume_share", text="second"),
            statement("next_action", text="a", timing="now"),
            statement("next_action", text="b", timing="later"),
        ],
        kinds=kinds,
    )
    assert [t.removeprefix(ASSUMPTION["en"]).strip() for t in texts] == ["first", "a", "b"]
    assert tally.rejected == 1


def test_a_kind_the_prompt_did_not_ask_for_is_rejected() -> None:
    assert rejected(statement("volume_share"), kinds=ASSESSMENT_KINDS)
    assert rejected(statement("strength"), kinds=RECOMMENDATION_KINDS)


def test_a_claim_on_a_buyer_context_that_does_not_exist_is_rejected() -> None:
    claim = statement("volume_share", cites_buyer_context=True)
    assert rejected(claim, kinds=RECOMMENDATION_KINDS)
    texts, _ = run([claim], kinds=RECOMMENDATION_KINDS, context=BuyerContext(3, "Incumbent."))
    assert texts == ["A statement."]  # with a context: no assumption, the claim is allowed


def test_the_assumption_is_put_in_front_of_recommendations_only_without_context() -> None:
    texts, _ = run(
        [statement("procurement_implication", text="Qualify first.")], RECOMMENDATION_KINDS
    )
    assert texts == ["Assuming a first evaluation of this supplier: Qualify first."]
    texts, _ = run(
        [statement("procurement_implication", text="Qualifier d'abord.")],
        RECOMMENDATION_KINDS,
        language="fr",
    )
    assert texts == ["En supposant une première évaluation de ce fournisseur : Qualifier d'abord."]
    texts, _ = run([statement("strength", text="Plain.")])
    assert texts == ["Plain."]  # not a recommendation


def test_the_assumption_is_not_added_twice() -> None:
    once = with_assumption("Assuming a first evaluation of this supplier: x", "en")
    assert once.count("Assuming") == 1


def test_an_item_that_does_not_match_the_schema_is_not_a_statement() -> None:
    assert to_statement(RawAssessmentStatement(kind="approve_supplier", text="x")) is None
    assert to_statement(RawAssessmentStatement(kind="strength", text="  ")) is None
    assert to_statement(RawAssessmentStatement(kind="strength", text="x", level="10")) is None
