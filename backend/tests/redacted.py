"""Test helper: text declared as already redacted, for tests that are not about redaction."""

from app.redaction.text import RedactedText, mint


def redacted(text: str) -> RedactedText:
    return mint(text)
