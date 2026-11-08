"""The validation rules of the assessment draft (spec F8; #25), in code and not in a prompt.

A drafted statement is kept only when every rule below holds; otherwise it is rejected and
counted. The model's answer is data: nothing in it is executed, and nothing in a fact's value or
quote can change a rule here.

- It cites only facts of this run that have a kept value (`proposed`, `approved`, `corrected`):
  never an id of another run, never a `not_found` fact, never a fact of a field flagged
  `concerns_people` in the profile definition (no statement evaluates an individual employee or
  manager).
- It cites at least one fact, unless it is an evidence gap, which names the missing evidence in
  `gap_evidence`. A level goes with cited facts only.
- `label` goes with `relationship_level` (required), `timing` with `next_action` (required),
  `level` is required for `procurement_priority`.
- It does not claim to rest on a buyer context that does not exist, and with no buyer context
  stored its text does not assert an existing relationship with the supplier ("your incumbent",
  "votre fournisseur actuel": a guard on the wording, #26).
- An evidence gap on financial stability is never drafted by the model (the financial guidance
  writes that message, #26).
- A recommendation kind other than `next_action` is kept once.

The first-evaluation assumption is put in front of every recommendation by code when the run has
no buyer context. It states an assumption about the evaluation, never a fact about the buyer.
"""

import re
from dataclasses import dataclass
from typing import Final

from pydantic import ValidationError

from app.llm_schemas import (
    ASSESSMENT_KINDS,
    RECOMMENDATION_KINDS,
    AssessmentStatement,
    RawAssessmentStatement,
)

KEPT_FACT_STATUSES: Final = ("proposed", "approved", "corrected")
ONCE_ONLY: Final = tuple(kind for kind in RECOMMENDATION_KINDS if kind != "next_action")

ASSUMPTION: Final = {
    "en": "Assuming a first evaluation of this supplier:",
    "fr": "En supposant une première évaluation de ce fournisseur :",
}
NOT_ASSESSED: Final = "Not assessed: natural-person business"

# Words of a financial-stability gap, in English and French. A gap whose text or missing evidence
# matches is dropped: #26 supplies that message, from rules and the country table.
_FINANCIAL: Final = re.compile(
    r"financ|revenue|turnover|balance sheet|accounts\b|profit|solven|insolven|credit|"
    r"liquidity|cash flow|bankrupt|creditworth|"
    r"chiffre d.affaires|bilan|comptes|solvab|liquidit|trésorerie|faillite|rentabilit|"
    r"capacité financière|\bdette",
    re.IGNORECASE,
)


# Wording that asserts an existing relationship with the supplier (spec F8: no statement asserts
# a fact about the buyer that was not entered), in English and French. A guard on the text, not a
# test of truth. The buyer must be the possessor ("your", "votre", "vos", "notre"): "the current
# supplier of the market" or "your existing quality systems" assert nothing about the buyer.
# With no context stored, any such wording is rejected; with the relationship `new`, it contradicts
# what the buyer entered and is rejected too; with `incumbent` it is allowed.
_BUYER_SITUATION = re.compile(
    r"\byour\s+(?:current|existing|incumbent|present|ongoing)\s+"
    r"(?:suppliers?|vendors?|providers?|partners?|contracts?|relationships?|arrangements?)\b|"
    r"\byour\s+incumbent\b|"
    r"\bas\s+(?:your\s+|the\s+|an?\s+)?(?:current|existing|incumbent)\s+(?:supplier|vendor|provider)|"
    r"\bas\s+(?:your\s+|the\s+|an?\s+)?incumbent\b|"
    r"\byou\s+(?:already|currently)\s+(?:buy|source|purchase|use|work|trade|contract)|"
    r"\b(?:we|you)\s+(?:already\s+)?(?:buy|source|purchase)\s+from\b|"
    r"\b(?:votre|notre)\s+(?:fournisseur\s+)?(?:actuel|historique|en\s+place|titulaire)\b|"
    r"\b(?:votre|notre)\s+(?:contrat|relation|part|volume)\s+(?:actuel|actuelle|en\s+cours|existant)|"
    r"\ben\s+tant\s+que\s+(?:votre\s+|notre\s+)?fournisseur\s+(?:actuel|historique|en\s+place|titulaire)|"
    r"\bvous\s+(?:achetez|travaillez|vous\s+approvisionnez)\s+(?:déjà|actuellement)|"
    r"\bvous\s+(?:achetez|vous\s+approvisionnez)\s+déjà|"
    r"\bvos\s+achats\s+actuels",
    re.IGNORECASE,
)


def asserts_buyer_situation(text: str) -> bool:
    """The text asserts an existing relationship with the supplier (a guard, not a truth test)."""
    return bool(_BUYER_SITUATION.search(text))


@dataclass(frozen=True)
class FactView:
    """A fact of the run, as the assessment sees it."""

    id: str
    field: str
    status: str
    value: str | None
    quote: str | None
    concerns_people: bool = False
    source_type: str | None = None  # "supplier_claim" or "third_party" (spec F3)

    @property
    def usable(self) -> bool:
        """It has a kept value and is not about a person: it can be shown to the model and cited."""
        return self.status in KEPT_FACT_STATUSES and not self.concerns_people


@dataclass(frozen=True)
class BuyerContext:
    """The buyer context of the run (entered with #27; none exists before)."""

    version: int
    text: str
    relationship: str | None = None  # "incumbent" or "new", as entered


@dataclass
class Tally:
    rejected: int = 0
    invalid: int = 0


def normalise_id(value: str) -> str:
    return value.strip().lower()


def to_statement(raw: RawAssessmentStatement) -> AssessmentStatement | None:
    """The item as an `AssessmentStatement`, or None when it does not match the schema."""
    try:
        return AssessmentStatement.model_validate(raw.model_dump(exclude_none=True))
    except ValidationError:
        return None


def is_financial_gap(statement: AssessmentStatement) -> bool:
    if statement.kind != "evidence_gap":
        return False
    return bool(_FINANCIAL.search(f"{statement.text} {statement.gap_evidence or ''}"))


def _cited_ok(statement: AssessmentStatement, facts: dict[str, FactView]) -> list[str] | None:
    """The normalised, de-duplicated cited ids when every one is a usable fact of the run."""
    cited: list[str] = []
    for raw in statement.cited_fact_ids:
        key = normalise_id(raw)
        fact = facts.get(key)
        if fact is None or not fact.usable:
            return None  # not in this run, not_found, or a field about people
        if key not in cited:
            cited.append(key)
    return cited


def check(
    statement: AssessmentStatement,
    allowed_kinds: tuple[str, ...],
    facts: dict[str, FactView],
    context: BuyerContext | None,
) -> list[str] | None:
    """The cited fact ids (normalised) of a statement that passes every rule, else None."""
    if statement.kind not in allowed_kinds:
        return None
    if statement.cites_buyer_context and context is None:
        return None  # the buyer's situation was not entered: nothing may rest on it
    if (context is None or context.relationship == "new") and asserts_buyer_situation(
        statement.text
    ):
        # "your incumbent...": a fact about the buyer that was not entered, or that contradicts
        # the relationship `new` the buyer entered.
        return None
    cited = _cited_ok(statement, facts)
    if cited is None:
        return None
    is_gap = statement.kind == "evidence_gap"
    if not cited and not is_gap:
        return None
    if statement.level is not None and not cited:
        return None
    gap = (statement.gap_evidence or "").strip()
    if is_gap != bool(gap):
        return None  # a gap names the missing evidence; nothing else carries gap evidence
    if (statement.kind == "relationship_level") != (statement.label is not None):
        return None
    if (statement.kind == "next_action") != bool((statement.timing or "").strip()):
        return None
    if statement.kind == "procurement_priority" and statement.level is None:
        return None
    if is_financial_gap(statement):
        return None
    return cited


def with_assumption(text: str, language: str) -> str:
    """`text` behind the first-evaluation assumption (once)."""
    assumption = ASSUMPTION.get(language, ASSUMPTION["en"])
    stripped = text.strip()
    if any(stripped.casefold().startswith(value.casefold()) for value in ASSUMPTION.values()):
        return stripped
    return f"{assumption} {stripped}"


@dataclass(frozen=True)
class Kept:
    statement: AssessmentStatement
    cited: tuple[str, ...]  # normalised fact ids
    text: str  # the stored text: with the assumption in front of a recommendation, when due
    buyer_context_version: int | None


def validate(
    statements: list[AssessmentStatement],
    allowed_kinds: tuple[str, ...],
    facts: dict[str, FactView],
    context: BuyerContext | None,
    language: str,
    tally: Tally,
) -> list[Kept]:
    """The statements that pass the rules, in order; the others are counted on `tally`."""
    kept: list[Kept] = []
    seen: set[str] = set()
    for statement in statements:
        cited = check(statement, allowed_kinds, facts, context)
        if cited is None or (statement.kind in ONCE_ONLY and statement.kind in seen):
            tally.rejected += 1
            continue
        seen.add(statement.kind)
        text = statement.text.strip()
        if statement.kind in RECOMMENDATION_KINDS and context is None:
            text = with_assumption(text, language)
        kept.append(
            Kept(statement, tuple(cited), text, context.version if context is not None else None)
        )
    return kept


__all__ = [
    "ASSESSMENT_KINDS",
    "ASSUMPTION",
    "NOT_ASSESSED",
    "RECOMMENDATION_KINDS",
    "BuyerContext",
    "FactView",
    "Kept",
    "Tally",
    "asserts_buyer_situation",
    "check",
    "to_statement",
    "validate",
    "with_assumption",
]
