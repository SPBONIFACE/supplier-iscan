"""What a run that stopped at its cost budget reports (#30): the sections not covered, and a plain
explanation of what was and was not done.

A section the run did not reach is not "No public evidence found": nobody looked. So the facts of
an uncovered section are absent, never stored as `not_found`, and the explanation says so.
"""

from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Fact, ProfileRun, SupplierIdentity
from app.profile_definition import ProfileDefinition

# The recommendations are not a section of the profile definition: this reserved id stands for them.
RECOMMENDATIONS: Final = "recommendations"
ASSESSMENT_PART: Final = "assessment"

WHAT: Final = {
    "collection": (
        "It stopped while collecting sources: the search for further sources was not made, "
        "so no facts were extracted and no assessment was drafted."
    ),
    "extraction": (
        "It stopped while extracting facts: the sections below were not extracted, or only "
        "partly, and no assessment was drafted."
    ),
    "assessment": (
        "It stopped while drafting the assessment: the statements drafted so far are kept, "
        "and the parts below were not drafted."
    ),
}
RECOMMENDATIONS_NAME: Final = "procurement recommendations"


def uncovered_sections(
    db: Session, run: ProfileRun, definition: ProfileDefinition, done: frozenset[str]
) -> list[str]:
    """The ids of the sections not covered, in the order of the definition, then
    `recommendations`. `done` holds the assessment parts that need no more work."""
    stored = set(db.scalars(select(Fact.field).where(Fact.run_id == run.id)))
    identity = db.scalar(select(SupplierIdentity).where(SupplierIdentity.id == run.identity_id))
    assessed = identity is None or not identity.natural_person  # never assessed: not "uncovered"
    uncovered = []
    for section in definition.sections:
        facts = [item.id for item in section.fields if item.kind == "fact"]
        has_assessment = any(item.kind == "assessment" for item in section.fields)
        if any(field not in stored for field in facts) or (
            assessed and has_assessment and ASSESSMENT_PART not in done
        ):
            uncovered.append(section.id)
    if assessed and RECOMMENDATIONS not in done:
        uncovered.append(RECOMMENDATIONS)
    return uncovered


def explanation(stage: str, uncovered: list[str], definition: ProfileDefinition) -> str:
    names = {section.id: section.labels.get("en", section.id) for section in definition.sections}
    names[RECOMMENDATIONS] = RECOMMENDATIONS_NAME
    listed = ", ".join(names.get(section, section) for section in uncovered) or "none"
    return (
        "The run stopped because it reached its cost budget. "
        f"{WHAT.get(stage, '')} Not covered: {listed}. "
        "These parts were not examined, so nothing is said about the supplier for them: it is "
        'not "No public evidence found". The sources, facts and statements produced before the '
        "stop are kept and can be read."
    ).replace("  ", " ")
