"""Redaction (#19): what is removed, what survives, forced names, fail closed, chunking.

Fast tests with a fake detector (`support.FakeDetector`): the rules, the company logic, the gate
around the detector. The real model is exercised in `test_model.py`.
"""

import logging
import re
from collections.abc import Sequence

import pytest

from app.redaction import (
    OMISSION,
    RedactedText,
    RedactionContext,
    RedactionUnavailable,
    Redactor,
)
from app.redaction import engine as engine_module
from app.redaction.detector import chunk_text
from tests.redaction.support import FakeDetector, fake_redactor


def redact(text: str, context: RedactionContext | None = None, *found: str) -> str:
    return fake_redactor(*found).redact(text, context).text


def test_a_detected_name_is_removed_and_the_role_and_each_omission_are_marked() -> None:
    out = redact(
        "Anna Meyer, Chief Executive Officer, wrote to bob.jones@example.org.", None, "Anna Meyer"
    )

    assert out == "[…], Chief Executive Officer, wrote to […]."


@pytest.mark.parametrize(
    "company",
    [
        "Acme Holdings Ltd",
        "Kaltenbach & Söhne Maschinenbau GmbH & Co. KG",
        "Aceros del Norte SL",
        "Ferramenta Lombarda SRL",
        "Metalurgica del Norte S.A.",
        "Fonderia Rossi S.p.A.",
    ],
)
def test_a_company_name_survives_when_the_detector_mislabels_it(company: str) -> None:
    text = f"{company} supplies the plant."

    assert redact(text, None, company) == text
    assert redact(text, None, company.split(" ")[0]) == text


def test_a_name_that_is_not_a_company_is_still_removed() -> None:
    assert redact("Hijos de Villaescusa is a family.", None, "Villaescusa") != (
        "Hijos de Villaescusa is a family."
    )


@pytest.mark.parametrize(
    ("phone", "form"),
    [
        ("+33 1 23 45 67 89", "+33 with spaces"),
        ("+33 1.23.45.67.89", "+33 with dots"),
        ("+49 30 1234567", "+49"),
        ("+49 (0)89 636-00", "+49 with brackets"),
        ("01 42 68 53 00", "French national"),
        ("030 123456", "German national"),
        ("+44 20 7946 0958", "UK"),
        ("+1 415 555 2671", "US"),
    ],
)
def test_phone_numbers_in_international_formats_are_removed(phone: str, form: str) -> None:
    out = redact(f"the line is {phone} today.")

    assert out == f"the line is {OMISSION} today.", form


@pytest.mark.parametrize(
    "identifier",
    [
        "SIREN 552 081 317",
        "SIRET 552 081 317 00022",
        "LEI 969500T3MBS4SQAMHJ45",
        "LEI 5493001KJTIIGC8Y1R12",
        "TVA FR40 303 265 045",
        "VAT DE811115368",
        "USt-IdNr. DE811115368",
        "VAT GB123456789",
        "Partita IVA IT12345678901",
        "NIF B12345678",
        "ISO 27001:2013",
        "revenue 1 234 567 890 EUR",
        "order 4500123456",
    ],
)
def test_identifiers_and_figures_are_not_taken_for_phone_numbers(identifier: str) -> None:
    text = f"the entry is {identifier}."
    assert redact(text) == text


def test_a_name_in_a_suppression_entry_is_redacted_ignoring_case_and_accents() -> None:
    context = RedactionContext(names=("Zoë Müller-Lüdenscheidt", "Hans Müller"))
    texts = [
        "zoe muller-ludenscheidt manages the plant",
        "ZOË MÜLLER LÜDENSCHEIDT manages the plant",
        "Zoe Mueller-Luedenscheidt manages the plant",
        "hans MUELLER manages the plant",
        "HANS MÜLLER manages the plant",
    ]

    for text in texts:
        assert redact(text, context) == f"{OMISSION} manages the plant", text


def test_a_forced_name_is_redacted_even_when_detection_misses_it() -> None:
    text = "see zorro quimby (lower case, no context)"

    assert "quimby" in redact(text)  # detection alone does not find it
    assert "quimby" not in redact(text, RedactionContext(names=("Zorro Quimby",)))


def test_a_natural_person_identity_loses_name_and_address_a_company_keeps_its_name() -> None:
    address = "Rue des Lilas 14, 69003 Lyon, FR"
    text = "Jean-Luc Martel Conseil, Rue des Lilas 14, 69003 Lyon, FR. Agent: Jean-Luc Martel."
    natural = RedactionContext(names=("Jean-Luc Martel",), addresses=(address,))

    person_out = redact(text, natural)
    company_out = redact(
        "Acme Supplies SA operates from Rue des Lilas 14, 69003 Lyon.",
        RedactionContext(keep=("Acme Supplies SA",)),
    )

    assert "Martel" not in person_out and "Rue des Lilas" not in person_out
    assert "69003" not in person_out
    assert "Acme Supplies SA" in company_out


def test_a_registry_company_name_is_protected_from_ner_but_not_from_forced_names() -> None:
    found = "Brightwater Anders"
    kept = redact("Brightwater Anders delivered.", RedactionContext(keep=(found,)), found)
    forced = redact(
        "Brightwater Anders delivered.",
        RedactionContext(keep=(found,), names=(found,)),
        found,
    )

    assert kept == "Brightwater Anders delivered."
    assert forced == f"{OMISSION} delivered."


def test_text_without_personal_data_is_unchanged() -> None:
    text = "The company reported revenue of EUR 12.5 million and 240 employees in 2023."

    assert redact(text) == text
    assert redact("") == ""


def test_long_text_is_cut_into_overlapping_chunks_and_nothing_is_lost() -> None:
    sentence = "Our Chief Executive Officer, Anna Meyer, signed the report. "
    text = sentence * (4 * 1_200 // len(sentence))
    detector = FakeDetector(["Anna Meyer"])

    out = Redactor(detector).redact(text).text

    assert "Meyer" not in out and out.count(OMISSION) == text.count("Anna Meyer")
    assert len(chunk_text(text)) > 3


@pytest.mark.parametrize("name", ["Anna Meyer", "Hollis Varney-Quick", "Thibaut de la Fresnaye"])
def test_a_name_on_a_chunk_boundary_lies_whole_in_one_chunk(name: str) -> None:
    for shift in range(0, 60):
        filler = "lorem ipsum dolor sit amet " * 60
        text = filler[: 1_200 - shift] + name + " " + filler
        assert any(name in piece for _, piece in chunk_text(text)), shift


def test_chunks_cover_every_position_with_a_stable_offset() -> None:
    text = ("word " * 900) + "\n" + ("x" * 3_000) + " end"

    pieces = chunk_text(text)

    covered = [False] * len(text)
    for offset, piece in pieces:
        assert text[offset : offset + len(piece)] == piece
        assert len(piece) <= 1_200
        for index in range(offset, offset + len(piece)):
            covered[index] = True
    assert all(covered)


def test_a_chunk_never_holds_more_words_than_the_model_reads() -> None:
    text = ", ".join(["a"] * 2_000)

    for _, piece in chunk_text(text, max_words=300):
        assert sum(1 for _ in re.finditer(r"\w+(?:[-_]\w+)*|\S", piece)) <= 300


def test_a_chunk_that_errors_fails_closed_without_the_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class SecondChunkFails(FakeDetector):
        def person_spans(self, texts: Sequence[str]) -> list[list[tuple[int, int]]]:
            if any("secret-person" in text for text in texts):
                raise RuntimeError("boom secret-person")
            return super().person_spans(texts)

    text = "calm text. " * 50 + "secret-person"
    with caplog.at_level(logging.DEBUG), pytest.raises(RedactionUnavailable) as error:
        Redactor(SecondChunkFails()).redact(text)

    assert "secret-person" not in str(error.value) and "secret-person" not in caplog.text
    assert error.value.__cause__ is None


def test_a_text_over_the_limit_is_refused_not_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module, "MAX_TEXT_CHARS", 100)

    with pytest.raises(RedactionUnavailable):
        redact("x" * 101)


def test_the_models_are_loaded_once_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    loads: list[str] = []

    class Counting(FakeDetector):
        def load(self) -> None:
            loads.append("gliner")

    class CountingHan(Counting):
        def load(self) -> None:
            loads.append("zh")

    monkeypatch.setattr(engine_module, "GlinerDetector", Counting)
    monkeypatch.setattr(engine_module, "SpacyHanDetector", CountingHan)
    redactor = Redactor()

    for _ in range(3):
        redactor.redact("Anna Meyer called.")

    assert sorted(loads) == ["gliner", "zh"]


def test_the_han_detector_is_used_only_for_han_text_and_united_with_the_main_one() -> None:
    main, han = FakeDetector(["Anna Meyer"]), FakeDetector(["王浩然"])
    redactor = Redactor(main, han)

    out = redactor.redact("Anna Meyer und 王浩然 sprachen. Anna Meyer allein.").text
    redactor.redact("Only Latin text here.")

    assert "Meyer" not in out and "王" not in out
    assert len(han.calls) == 1


def test_a_model_that_cannot_be_loaded_fails_closed_without_the_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: pytest.TempPathFactory,
) -> None:
    monkeypatch.setenv("REDACTION_MODEL_DIR", str(tmp_path))

    with caplog.at_level(logging.DEBUG), pytest.raises(RedactionUnavailable) as error:
        Redactor().redact("Anna Meyer, anna@example.org")

    assert "Anna" not in str(error.value) and "Anna" not in caplog.text
    assert error.value.__cause__ is None


def test_an_exception_during_redaction_fails_closed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def explode(text: str) -> list[tuple[int, int]]:
        raise RuntimeError(f"boom with {text}")

    monkeypatch.setattr(engine_module, "_email_spans", explode)

    with caplog.at_level(logging.DEBUG), pytest.raises(RedactionUnavailable) as error:
        fake_redactor().redact("Anna Meyer, anna@example.org")

    assert "Anna" not in str(error.value) and "Anna" not in caplog.text
    assert error.value.__cause__ is None


def test_a_detector_that_raises_fails_closed() -> None:
    redactor = Redactor(FakeDetector(fail_on="Anna"))

    with pytest.raises(RedactionUnavailable):
        redactor.redact("Anna Meyer called.")


def test_redacted_text_cannot_be_created_outside_the_redaction_module() -> None:
    with pytest.raises(TypeError):
        RedactedText("Anna Meyer")
    with pytest.raises(TypeError):
        RedactedText("Anna Meyer", _token=object())
    secret = fake_redactor("Anna Meyer").redact("Reach Anna Meyer.")
    assert "Anna" not in repr(secret) and "Anna" not in str(secret)
    with pytest.raises(AttributeError):
        secret._chars = "Anna Meyer"
