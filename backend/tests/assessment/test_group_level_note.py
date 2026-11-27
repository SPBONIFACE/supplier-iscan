"""#195: the assessment prompt says which facts are group level."""

from app.assessment.rules import FactView
from app.assessment.stage import GROUP_LEVEL_NOTE, facts_text


def fact(**changes: object) -> FactView:
    values: dict[str, object] = {
        "id": "f1",
        "field": "revenue",
        "status": "proposed",
        "value": "13.6 billion",
        "quote": "Amcor reported sales of 13.6 billion dollars",
    }
    values.update(changes)
    return FactView(**values)  # type: ignore[arg-type]


def test_a_group_level_fact_is_marked_and_the_prompt_says_not_to_present_it_as_the_entitys() -> (
    None
):
    text = facts_text([fact(group_level="Amcor plc"), fact(id="f2", field="employee_count")], {})

    assert text.startswith(GROUP_LEVEL_NOTE)
    lines = text.splitlines()
    assert 'group_level="Amcor plc"' in lines[1] and "group_level" not in lines[2]


def test_the_note_covers_another_entity_of_the_group_and_the_parent_group() -> None:
    # #209: the label may name a sister company as well as the parent group.
    assert "another entity of the group" in GROUP_LEVEL_NOTE
    assert "parent group" in GROUP_LEVEL_NOTE
    assert "never about the supplier entity" in GROUP_LEVEL_NOTE


def test_without_a_group_level_fact_the_text_is_unchanged() -> None:
    text = facts_text([fact()], {})

    assert "group_level" not in text
