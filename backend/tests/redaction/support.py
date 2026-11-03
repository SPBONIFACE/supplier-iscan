"""Test doubles and helpers for redaction tests (#19)."""

import re
from collections.abc import Sequence

from app.redaction import Redactor

Span = tuple[int, int]


class FakeDetector:
    """A name detector for the fast tests: it "finds" the listed names (ignoring case) wherever
    they occur, and nothing else. `fail_on` makes it raise on a text containing that word."""

    def __init__(self, found: Sequence[str] = (), fail_on: str | None = None) -> None:
        self._patterns = [re.compile(re.escape(name), re.IGNORECASE) for name in found]
        self._fail_on = fail_on
        self.calls: list[list[str]] = []

    def person_spans(self, texts: Sequence[str]) -> list[list[Span]]:
        self.calls.append(list(texts))
        if self._fail_on and any(self._fail_on in text for text in texts):
            raise RuntimeError("boom")
        return [
            [match.span() for pattern in self._patterns for match in pattern.finditer(text)]
            for text in texts
        ]


def fake_redactor(*found: str) -> Redactor:
    return Redactor(FakeDetector(found))
