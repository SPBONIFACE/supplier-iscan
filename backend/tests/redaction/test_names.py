"""Names in capitals, honorifics, labels, noise and obfuscated emails (#19, QA defects)."""

from collections import defaultdict

import pytest

from app.redaction import OMISSION, get_redactor
from tests.redaction.measure_names import leaked
from tests.redaction.name_corpus import (
    NAMES_B,
    NON_PERSON,
    honorific_cases,
    name_cases,
)


def redact(text: str) -> str:
    return get_redactor().redact(text).text


@pytest.mark.parametrize(
    ("text", "gone", "kept"),
    [
        (
            "Contact: JEAN DUPONT, Purchasing Director",
            ("JEAN", "DUPONT"),
            ("Purchasing Director",),
        ),
        ("Mme FONTAINE will call back.", ("FONTAINE",), ("Mme",)),
        ("The visit of M. Thierry Vasseur was short.", ("Thierry", "Vasseur"), ("M.",)),
        ("Mr Price signed the order.", ("Price",), ("Mr",)),
        ("Dr. J. WHITMORE chairs the committee.", ("WHITMORE",), ("Dr.",)),
        ("Étienne\nMARCHETTI\nDirecteur des achats", ("Étienne", "MARCHETTI"), ("Directeur",)),
        ("Signé par Anaïs Delorme", ("Anaïs", "Delorme"), ("Signé par",)),
        ("Ansprechpartner: Frieda KRAUSE-LEHNER, Leiterin", ("KRAUSE", "LEHNER"), ("Leiterin",)),
        ("Herr von Salm sagte zu.", ("Salm",), ("Herr",)),
        ("Jean Price will call.", ("Price",), ()),
        ("Contact: Joaquín del OLMO\nPurchasing", ("OLMO", "Joaquín"), ("Purchasing",)),
    ],
)
def test_capitals_honorifics_and_labels_take_the_whole_name(
    text: str, gone: tuple[str, ...], kept: tuple[str, ...]
) -> None:
    out = redact(text)

    assert OMISSION in out
    for item in gone:
        assert item not in out, (item, out)
    for item in kept:
        assert item in out, (item, out)


@pytest.mark.parametrize(
    "text",
    [
        "ISO 9001:2015, ISO 14001",
        "Certified: ISO 9001:2015, ISO 14001:2015, IATF 16949, EN 10204 3.1, DIN EN ISO 13485",
        "Registered office",
        "Price",
        "Call",
        "Signé",
        "Contact us for a quotation.",
        "ACME GMBH",
        "PURCHASING DIRECTOR",
        "ISO 45001 AND ISO 14001 CERTIFIED",
        "Siège social : 8 rue de la Paix, 75002 Paris",
        "Signé à Lyon, le 4 mars 2025.",
    ],
)
def test_standards_common_words_and_companies_are_not_names(text: str) -> None:
    assert redact(text) == text


def test_over_redaction_of_non_person_text_is_under_two_percent() -> None:
    changed = [line for line in NON_PERSON if redact(line) != line]

    assert len(changed) / len(NON_PERSON) < 0.02, changed


def test_recall_on_a_fresh_synthetic_corpus() -> None:
    """Names never used to tune the rules: normal and "Jean DUPONT" >= 95%, ALL CAPS >= 90%."""
    redactor = get_redactor()
    cases = [*name_cases(NAMES_B, 3), *honorific_cases(NAMES_B, 3)]
    score: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    honorific_leaks: list[str] = []
    for case in cases:
        out = redactor.redact(case.text).text
        ok = not leaked(case, out) and (case.role not in case.text or case.role in out)
        group = "all_caps" if case.casing == "all_caps" else "other"
        score[group][0] += int(ok)
        score[group][1] += 1
        if case.context == "honorific" and any(
            part.casefold() in out.casefold() for part in case.name_parts[-1:]
        ):
            honorific_leaks.append(case.text)

    assert score["other"][0] / score["other"][1] >= 0.95, score
    assert score["all_caps"][0] / score["all_caps"][1] >= 0.90, score
    assert len(honorific_leaks) <= 1, honorific_leaks


@pytest.mark.parametrize(
    "text",
    [
        "Write to jean [at] acme [dot] com today.",
        "Write to jean(at)acme.com today.",
        "Write to jean (at) acme (dot) com today.",
        "Write to jean at acme dot com today.",
        "Write to jean.dupont[at]acme[dot]co[dot]uk today.",
        "Écrire à jean arobase acme point com.",
    ],
)
def test_obfuscated_email_addresses_are_removed(text: str) -> None:
    out = redact(text)

    assert "acme" not in out
    assert OMISSION in out


@pytest.mark.parametrize(
    "text",
    [
        "We arrive at noon.",
        "Meet me at acme.com on Monday.",
        "The meeting is at 10 (at the latest) in the hall.",
        "Look at the plan [at the end] for details.",
        "Prices start at nine euros a day.",
        "It is a dot on the map at the top.",
    ],
)
def test_ordinary_prose_with_at_and_dot_is_untouched(text: str) -> None:
    assert redact(text) == text
