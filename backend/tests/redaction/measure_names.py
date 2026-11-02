"""Recall on generated names and over-redaction (`python -m tests.redaction.measure_names`)."""

import sys
from collections import defaultdict

from app.redaction import get_redactor
from tests.redaction.name_corpus import (
    NAMES_A,
    NAMES_B,
    NON_PERSON,
    NameCase,
    honorific_cases,
    name_cases,
)


def leaked(case: NameCase, out: str) -> bool:
    folded = out.casefold()
    return any(part.casefold() in folded for part in case.name_parts)


def altered() -> list[str]:
    redactor = get_redactor()
    return [line for line in NON_PERSON if redactor.redact(line).text != line]


def main() -> None:
    names = NAMES_B if "--fresh" in sys.argv else NAMES_A
    redactor = get_redactor()
    count = 4 if "--quick" in sys.argv else 8
    cases = [*name_cases(names, count), *honorific_cases(names, count)]
    totals: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    by_context: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    misses: list[str] = []
    for case in cases:
        out = redactor.redact(case.text).text
        ok = not leaked(case, out) and (case.role not in case.text or case.role in out)
        totals[(case.language, case.casing)][0] += int(ok)
        totals[(case.language, case.casing)][1] += 1
        by_context[(case.casing, case.context)][0] += int(ok)
        by_context[(case.casing, case.context)][1] += 1
        if not ok:
            misses.append(f"{case.language}/{case.context}/{case.casing}: {case.text!r} -> {out!r}")
    for key, (hits, total) in sorted(totals.items()):
        print(f"{key[0]} {key[1]:<20} {hits}/{total} = {hits / total:.3f}")
    for key, (hits, total) in sorted(by_context.items()):
        print(f"{key[0]:<20} {key[1]:<12} {hits}/{total} = {hits / total:.3f}")
    changed = altered()
    print(f"over-redaction: {len(changed)}/{len(NON_PERSON)}", changed)
    if "-v" in sys.argv:
        print("\n".join(misses))


if __name__ == "__main__":
    main()
