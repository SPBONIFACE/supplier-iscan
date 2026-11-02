"""Redaction (#19): what is removed, what survives, forced names, fail closed, performance."""

import logging

import pytest
import spacy

from app.redaction import (
    OMISSION,
    RedactedText,
    RedactionContext,
    RedactionUnavailable,
    Redactor,
    get_redactor,
)
from app.redaction import engine as engine_module
from tests.redaction.corpora import COMPANY_CASES, CORPUS, HELD_OUT, Case


def redact(text: str, context: RedactionContext | None = None) -> str:
    return get_redactor().redact(text, context).text


@pytest.mark.parametrize("case", [*CORPUS, *HELD_OUT], ids=lambda c: f"{c.language}-{c.text[:30]}")
def test_personal_data_is_removed_and_roles_companies_and_identifiers_survive(case: Case) -> None:
    out = redact(case.text)

    for item in case.remove:
        assert item not in out, item
    for item in case.keep:
        assert item in out, item
    assert OMISSION in out


@pytest.mark.parametrize("case", COMPANY_CASES, ids=lambda c: c.language)
def test_a_company_name_survives_when_ner_mislabels_it(case: Case) -> None:
    out = redact(case.text)

    for item in case.keep:
        assert item in out


def test_the_role_stays_and_each_omission_is_marked() -> None:
    out = redact("Anna Meyer, Chief Executive Officer, wrote to bob.jones@example.org.")

    assert out == "[…], Chief Executive Officer, wrote to […]."


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
    kept = redact("Brightwater Anders delivered.", RedactionContext(keep=("Brightwater Anders",)))
    forced = redact(
        "Brightwater Anders delivered.",
        RedactionContext(keep=("Brightwater Anders",), names=("Brightwater Anders",)),
    )

    assert kept == "Brightwater Anders delivered."
    assert forced == f"{OMISSION} delivered."


def test_text_without_personal_data_is_unchanged() -> None:
    text = "The company reported revenue of EUR 12.5 million and 240 employees in 2023."

    assert redact(text) == text
    assert redact("") == ""


def test_long_text_is_processed_in_bounded_chunks() -> None:
    sentence = "Our Chief Executive Officer, Anna Meyer, signed the report. "
    text = sentence * (3 * engine_module.CHUNK_CHARS // len(sentence))

    out = redact(text)

    assert "Meyer" not in out and "Chief Executive Officer" in out
    assert out.count(OMISSION) >= text.count("Anna Meyer") - 3


def test_a_text_over_the_limit_is_refused_not_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module, "MAX_TEXT_CHARS", 100)

    with pytest.raises(RedactionUnavailable):
        redact("x" * 101)


def test_the_models_are_loaded_once_per_process_and_only_the_ner_pipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loads: list[str] = []
    real_load = spacy.load

    def counting_load(name: str, **kwargs: object) -> object:
        loads.append(name)
        return real_load(name, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(spacy, "load", counting_load)
    redactor = Redactor()

    for _ in range(3):
        redactor.redact("Anna Meyer called.")

    assert sorted(loads) == [
        "de_core_news_sm",
        "en_core_web_sm",
        "xx_ent_wiki_sm",
        "zh_core_web_sm",
    ]
    assert all(nlp.pipe_names == ["ner"] for nlp in redactor._models.values())


def test_the_process_wide_redactor_is_one_object() -> None:
    assert get_redactor() is get_redactor()


def test_a_model_that_cannot_be_loaded_fails_closed_without_the_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(name: str, **kwargs: object) -> object:
        raise OSError(f"[E050] cannot find {name}: secret-person-name")

    monkeypatch.setattr(spacy, "load", broken)

    with caplog.at_level(logging.DEBUG), pytest.raises(RedactionUnavailable) as error:
        Redactor().redact("Anna Meyer, anna@example.org")

    assert "Anna" not in str(error.value) and "secret-person-name" not in str(error.value)
    assert "Anna" not in caplog.text and "secret-person-name" not in caplog.text
    assert error.value.__cause__ is None


def test_an_exception_during_redaction_fails_closed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    redactor = Redactor()
    redactor.load()

    def explode(text: str) -> list[tuple[int, int]]:
        raise RuntimeError(f"boom with {text}")

    monkeypatch.setattr(engine_module, "_email_spans", explode)

    with caplog.at_level(logging.DEBUG), pytest.raises(RedactionUnavailable) as error:
        redactor.redact("Anna Meyer, anna@example.org")

    assert "Anna" not in str(error.value) and "Anna" not in caplog.text
    assert error.value.__cause__ is None


def test_redacted_text_cannot_be_created_outside_the_redaction_module() -> None:
    with pytest.raises(TypeError):
        RedactedText("Anna Meyer")
    with pytest.raises(TypeError):
        RedactedText("Anna Meyer", _token=object())
    secret = get_redactor().redact("Reach Anna Meyer.")
    assert "Anna" not in repr(secret) and "Anna" not in str(secret)
    with pytest.raises(AttributeError):
        secret._chars = "Anna Meyer"
