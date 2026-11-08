"""Names in capitals, honorifics, labels, noise and obfuscated emails (#19, QA defects)."""

import pytest

from app.redaction import OMISSION, Redactor

pytestmark = pytest.mark.model
_REAL: list[Redactor] = []


@pytest.fixture(autouse=True)
def _use_real(real_redactor: Redactor) -> None:
    _REAL[:] = [real_redactor]


def redact(text: str) -> str:
    return _REAL[0].redact(text).text


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
