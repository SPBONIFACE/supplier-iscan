"""Measured detection per language over the corpora: `uv run python -m tests.redaction.measure`."""

from collections import defaultdict

from app.redaction import get_redactor
from tests.redaction.corpora import COMPANY_CASES, CORPUS, HELD_OUT, Case


def measure(cases: tuple[Case, ...]) -> dict[str, dict[str, list[str]]]:
    """Per language: what was removed, what was missed, what was wrongly lost."""
    redactor = get_redactor()
    result: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: {"removed": [], "missed": [], "lost": [], "kept": []}
    )
    for case in cases:
        out = redactor.redact(case.text).text
        for item in case.remove:
            (
                result[case.language]["removed"]
                if item not in out
                else result[case.language]["missed"]
            ).append(item)
        for item in case.keep:
            (
                result[case.language]["kept"] if item in out else result[case.language]["lost"]
            ).append(item)
    return result


def main() -> None:
    for title, cases in (
        ("tuning corpus", CORPUS),
        ("held-out", HELD_OUT),
        ("company names", COMPANY_CASES),
    ):
        print(f"== {title}")
        for language, row in sorted(measure(cases).items()):
            removed, missed = len(row["removed"]), len(row["missed"])
            kept, lost = len(row["kept"]), len(row["lost"])
            recall = removed / (removed + missed) if removed + missed else float("nan")
            survival = kept / (kept + lost) if kept + lost else float("nan")
            print(
                f"{language}: recall {removed}/{removed + missed} = {recall:.2f}; "
                f"survival {kept}/{kept + lost} = {survival:.2f}; "
                f"missed {row['missed']}; lost {row['lost']}"
            )


if __name__ == "__main__":
    main()
