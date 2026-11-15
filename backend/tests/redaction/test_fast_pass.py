"""The fast second pass for stored source text (#185): no detector, and no way to give it text
that never passed the detector."""

import pytest

from app.models import Source
from app.redaction import (
    OMISSION,
    RedactedText,
    RedactionGate,
    Redactor,
    StoredSourceText,
    concat,
)
from tests.redaction.support import FakeDetector


def stored(text: str) -> StoredSourceText:
    return StoredSourceText.of(Source(redacted_text=text))


def test_the_fast_pass_redacts_forced_names_addresses_emails_and_phones_without_the_detector() -> (
    None
):
    detector = FakeDetector(found=["Zed Zorn"])
    gate = RedactionGate(lambda: ["Tobias Reuter"], Redactor(detector))
    text = (
        "Tobias Reuter wrote to jean@acme.example. Zed Zorn stays. Jean Dupont lives at "
        "12 rue des Lilas, Lyon. Call +33 4 72 00 11 22. Acme Supplies SA is kept."
    )

    out = gate.redact_stored(
        stored(text), person_names=["Jean Dupont"], addresses=["12 rue des Lilas, Lyon"]
    )

    assert isinstance(out, RedactedText)
    assert out.text.count(OMISSION) >= 4
    for gone in ("Tobias Reuter", "jean@acme.example", "Jean Dupont", "Lilas", "72 00 11 22"):
        assert gone not in out.text
    assert "Zed Zorn" in out.text  # only the detector would find it
    assert "Acme Supplies SA" in out.text
    assert detector.calls == []


def test_the_full_gate_still_runs_the_detector_for_any_other_text() -> None:
    detector = FakeDetector(found=["Zed Zorn"])
    gate = RedactionGate(lambda: [], Redactor(detector))

    out = gate.redact("Zed Zorn asks.")

    assert "Zed Zorn" not in out.text
    assert detector.calls


def test_stored_text_cannot_be_made_from_a_string() -> None:
    with pytest.raises(TypeError):
        StoredSourceText("never passed the detector")
    with pytest.raises(TypeError):
        StoredSourceText.of("never passed the detector")  # type: ignore[arg-type]


def test_a_piece_must_be_part_of_the_stored_text() -> None:
    source = stored("one two three")
    assert source.piece("two").text == "two"
    with pytest.raises(ValueError):
        source.piece("four")


def test_concat_joins_redacted_pieces() -> None:
    gate = RedactionGate(lambda: [], Redactor(FakeDetector()))
    joined = concat([gate.redact("a "), gate.redact_stored(stored("b "))])
    assert joined.text == "a b "
