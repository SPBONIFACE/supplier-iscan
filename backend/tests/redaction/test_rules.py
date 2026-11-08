"""The precise rules around the detector (#19), with a detector that finds nothing: whatever is
removed here comes from the rules (honorific, label, capitals, table, lower-case clue)."""

import pytest

from app.redaction import OMISSION
from tests.redaction.support import fake_redactor


def redact(text: str) -> str:
    return fake_redactor().redact(text).text


@pytest.mark.parametrize(
    ("text", "gone", "kept"),
    [
        ("Contact: JEAN DUPONT, Purchasing Director", ("JEAN", "DUPONT"), ("Purchasing Director",)),
        ("Mme FONTAINE will call back.", ("FONTAINE",), ("Mme",)),
        ("The visit of M. Thierry Vasseur was short.", ("Thierry", "Vasseur"), ("M.",)),
        ("Mr Price signed the order.", ("Price",), ("Mr",)),
        ("Dr. J. WHITMORE chairs the committee.", ("WHITMORE",), ("Dr.",)),
        ("Herr von Salm sagte zu.", ("Salm",), ("Herr",)),
        ("Contact: Joaquín del OLMO\nPurchasing", ("OLMO", "Joaquín"), ("Purchasing",)),
        ("Contact: LI", ("LI",), ()),
        ("Name: WANG", ("WANG",), ()),
        ("Signe: ROY", ("ROY",), ()),
        ("Mme LI", ("LI",), ("Mme",)),
        ("m. dupont", ("dupont",), ("m.",)),
        ("jean dupont, directeur achats", ("jean", "dupont"), ("directeur achats",)),
        ("anna schmidt, head of purchasing", ("anna", "schmidt"), ("head of purchasing",)),
    ],
)
def test_a_name_with_a_clue_is_removed_by_the_rules_alone(
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
        "Registered office",
        "Price",
        "ACME GMBH",
        "PURCHASING DIRECTOR",
        "Siège social : 8 rue de la Paix, 75002 Paris",
        "Contact: HR",
        "Contact: EU",
        "Contact: our sales team",
        "contact: sales department",
        "head of purchasing",
        "5 m. long and 3 m. wide",
        "Regards,",
        "Company number 01234567",
        "we look at acme dot matrix printers",
        "meet at the office",
    ],
)
def test_ordinary_text_is_left_alone_by_the_rules(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "jean at acme dot com",
        "jean [at] acme [dot] com",
        "jean(at)acme.com",
        "jean AT ACME DOT COM",
    ],
)
def test_obfuscated_addresses_are_removed(text: str) -> None:
    assert "acme" not in redact(text).lower()


def test_a_role_line_after_a_name_stays() -> None:
    out = redact("Contact: Heike WIESINGER\nBuyer")

    assert "WIESINGER" not in out and "Buyer" in out


def test_a_lower_case_name_after_a_label_needs_the_detector_to_confirm() -> None:
    assert redact("contact: jean dupont") == "contact: jean dupont"
