"""#219: synthetic numeric tables (fixed seed) and the old phone rule, for the tests."""

import random
from typing import Final

import phonenumbers

from app.redaction import engine

PHONE: Final = "+41 79 555 01 23"


def table_rows(count: int, seed: int = 219) -> list[str]:
    """`count` rows of 4 grouped figures, as in a financial table (thousands groups, decimals)."""
    rng = random.Random(seed)  # noqa: S311 (test data, fixed seed)
    rows = []
    for _ in range(count):
        figures = []
        for _ in range(4):
            number = rng.randint(1_000, 99_999_999)
            figures.append(f"{number:,}".replace(",", " "))
        rows.append("  ".join(figures))
    return rows


def table(count: int, seed: int = 219) -> str:
    return "\n".join(table_rows(count, seed))


def one_line(count: int, seed: int = 219) -> str:
    """`count` figures on a single line."""
    rng = random.Random(seed)  # noqa: S311 (test data, fixed seed)
    return " ".join(f"{rng.randint(1_000, 999_999):,}".replace(",", " ") for _ in range(count))


def _old_accept_phone(text: str, start: int, end: int, raw: str) -> bool:
    """`_accept_phone` of `main` before #219 (without the grouped-figure guard)."""
    if start > 0 and (text[start - 1].isalnum()) or end < len(text) and text[end].isalnum():
        return False
    if raw.startswith(("+", "00")):
        return True
    if engine._ID_LABEL.search(text[max(0, start - 14) : start]) and not engine._PHONE_WORD.search(
        text[max(0, start - 40) : start]
    ):
        return False
    return raw.startswith(("0", "(")) or "-" in raw


def old_phone_spans(text: str) -> list[tuple[int, int]]:
    """The rule of `main` before #219, kept as the reference of the differential test."""
    spans: dict[tuple[int, int], bool] = {}
    text = engine._UUID.sub(lambda match: "x" * len(match.group()), text)
    for region in (None, *engine._PHONE_REGIONS):
        matcher = phonenumbers.PhoneNumberMatcher(
            text, region, leniency=phonenumbers.Leniency.VALID, max_tries=200
        )
        for match in matcher:
            raw = text[match.start : match.end]
            if _old_accept_phone(text, match.start, match.end, raw):
                spans[(match.start, match.end)] = True
    return list(spans)


PLAIN: Final = "The audit committee reviewed the controls of the plant and found them adequate. "
FIGURES: Final = "Revenue rose to 1 234 567 euros in 2024, up 12.5 percent, as the report states. "


def prose(characters: int, with_figures: bool) -> str:
    """Prose; with figures: a sentence with three figures every 100 sentences (about 1 per 3k)."""
    unit = PLAIN * 99 + (FIGURES if with_figures else PLAIN)
    return (unit * (characters // len(unit) + 1))[:characters]
