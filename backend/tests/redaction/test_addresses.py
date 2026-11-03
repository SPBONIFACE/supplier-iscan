"""A sole trader's registry address is forced out of every text (#19, owner decision, 2 Nov 2026).

Matched: case, accents, spacing, punctuation, line breaks; the street-word abbreviations of
`app.redaction.engine._ABBREVIATIONS` ("rue"/"r.", "Straße"/"Str.", "Hauptstraße"/"Hauptstr.",
"Street"/"St", "Avenue"/"Ave", "Boulevard"/"Bd", "Calle"/"C.", "Via"/"V."); the German
transliteration (ä as ae); the postcode and city alone; the street line alone. Not matched: other
abbreviations, a misspelling, an address split by words that are not in the stored address.
"""

import pytest

from app.redaction import OMISSION, RedactionContext
from tests.redaction.support import fake_redactor


def redact(text: str, *addresses: str) -> str:
    return fake_redactor().redact(text, RedactionContext(addresses=addresses)).text


@pytest.mark.parametrize(
    ("address", "text", "gone"),
    [
        (
            "14 Rue des Lilas, 69003 Lyon, France",
            "Siege: 14 RUE DES LILAS, 69003 LYON, FRANCE.",
            "LILAS",
        ),
        ("14 Rue des Lilas, 69003 Lyon, France", "au 14 r. des Lilas 69003 Lyon", "Lilas"),
        ("14 Rue des Lilas, 69003 Lyon, France", "14   rue\ndes   lilas,\n69003  Lyon", "lilas"),
        ("14 Rue des Lilas, 69003 Lyon, France", "14 rue des Lilàs (69003 Lyon)", "Lil"),
        ("14 Rue des Lilas, 69003 Lyon, France", "domicilié 14, rue des lilas", "lilas"),
        ("14 Rue des Lilas, 69003 Lyon, France", "code postal 69003 Lyon", "69003"),
        ("Hauptstraße 5, 10115 Berlin, Germany", "Hauptstr. 5, 10115 Berlin", "Hauptstr"),
        ("Hauptstr. 5, 10115 Berlin", "Hauptstrasse 5 10115 Berlin", "Hauptstrasse"),
        ("Müllerstraße 7, 80331 München", "Muellerstrasse 7, 80331 Muenchen", "Muellerstrasse"),
        ("Müllerstraße 7, 80331 München", "MÜLLERSTRASSE 7", "MÜLLERSTRASSE"),
        ("12 Mill Street, Leeds LS1 4AB, United Kingdom", "12 Mill St, Leeds LS1 4AB", "Mill"),
        ("12 Mill St., Leeds LS1 4AB", "12 mill street leeds ls1 4ab", "mill"),
        ("5 Park Avenue, New York 10001", "5 Park Ave., New York 10001", "Park"),
        ("Calle Mayor 3, 28013 Madrid, España", "C/ Mayor 3, 28013 Madrid", "Mayor"),
        ("Via Roma 10, 20121 Milano", "V. Roma 10 - 20121 Milano", "Roma"),
        ("Avenida de la Paz 8, 41001 Sevilla", "Avda. de la Paz, 8 41001 Sevilla", "Paz"),
    ],
)
def test_the_address_is_redacted_despite_case_accents_spacing_punctuation_and_abbreviations(
    address: str, text: str, gone: str
) -> None:
    out = redact(text, address)

    assert gone not in out, out
    assert OMISSION in out


def test_without_the_address_nothing_is_redacted() -> None:
    text = "Siege: 14 rue des Lilas, 69003 Lyon."

    assert redact(text) == text


def test_an_address_of_another_place_is_not_redacted() -> None:
    text = "Depot: 16 rue des Lilas, 69003 Lyon."

    out = redact(text, "14 Rue des Lilas, 69003 Lyon, France")

    assert "16 rue des Lilas" in out


def test_an_abbreviation_that_is_not_listed_is_not_matched() -> None:
    """Stated limit: only the groups of `_ABBREVIATIONS` are equivalent."""
    out = redact("14 rte des Lilas", "14 Rue des Lilas")

    assert "Lilas" in out
