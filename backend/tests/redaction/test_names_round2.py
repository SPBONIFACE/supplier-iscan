"""Second QA round (#19): short surnames after a label, ordinary text left alone, roles kept,
obfuscated e-mails in prose, and lower-case names found only from a clue."""

import pytest

from app.redaction import OMISSION, Redactor
from tests.redaction.lowercase_corpus import LOWER_PROSE, lower_case_cases

pytestmark = pytest.mark.model
_REAL: list[Redactor] = []


@pytest.fixture(autouse=True)
def _use_real(real_redactor: Redactor) -> None:
    _REAL[:] = [real_redactor]


def redact(text: str) -> str:
    return _REAL[0].redact(text).text


@pytest.mark.parametrize(
    ("text", "gone"),
    [
        ("Contact: LI", "LI"),
        ("Contact: ROY, acheteur", "ROY"),
        ("Name: WANG", "WANG"),
        ("Responsable: ROY", "ROY"),
        ("Ansprechpartner: LI", "LI"),
        ("Signe: ROY", "ROY"),
        ("Contacto: XU\nCompras", "XU"),
        ("M. ROY", "ROY"),
        ("Mme LI", "LI"),
        ("Mr WANG", "WANG"),
    ],
)
def test_a_short_all_caps_surname_after_a_label_or_honorific_is_redacted(
    text: str, gone: str
) -> None:
    out = redact(text)

    assert gone not in out
    assert OMISSION in out


@pytest.mark.parametrize("text", ["Contact: HR", "Contact: EU", "Contact: ISO", "Name: CEO"])
def test_an_acronym_after_a_label_is_not_a_surname(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "Best regards,",
        "Regards,",
        "Best wishes,",
        "Kind regards,",
        "Opening hours: Monday to Friday",
        "Thank you for your enquiry",
        "Fabricamos componentes de acero",
        "Cuscinetti a sfera",
        "Kugellager und Waelzlager",
        "Paris, Lyon, Marseille and Toulouse",
        "Barcelona and Valencia",
        "Milano, Torino, Bologna",
        "Offices in London, Manchester and Leeds",
        "Metalurgica del Norte S.A.",
        "Fonderia Rossi S.p.A.",
        "Officine Verdi S.r.l.s.",
        "Aciers du Nord SARL, Lyon",
        "Dunmore Valve Technology Ltd",
        "Müller & Söhne Armaturen GmbH & Co. KG",
        "ENVIRONMENTAL POLICY",
        "ALLGEMEINE GESCHAEFTSBEDINGUNGEN",
        "CODE OF CONDUCT FOR SUPPLIERS",
        "FICHA DE DATOS DE SEGURIDAD",
        "Company number 01234567",
        "Partita IVA: IT 01234567890",
    ],
)
def test_ordinary_text_is_not_redacted(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize(
    ("text", "gone", "kept"),
    [
        ("Regards,\nJohn\nBuyer", "John", "Buyer"),
        ("Best regards,\nJohn\nBuyer", "John", "Buyer"),
        ("Heike WIESINGER\nBuyer", "WIESINGER", "Buyer"),
        ("Cordialement,\nAnaïs Delorme\nAcheteuse", "Delorme", "Acheteuse"),
        ("Mit freundlichen Grüßen\nWolfram Hartwig\nEinkäufer", "Hartwig", "Einkäufer"),
    ],
)
def test_a_role_line_after_a_name_stays(text: str, gone: str, kept: str) -> None:
    out = redact(text)

    assert gone not in out
    assert kept in out


def test_a_legal_form_in_the_next_sentence_does_not_make_a_person_a_company() -> None:
    out = redact("She met Zoë Okonkwo-Lindqvist. Acme Supplies SA makes valves.")

    assert "Okonkwo" not in out
    assert "Acme Supplies SA" in out


@pytest.mark.parametrize(
    "text",
    [
        "we look at acme dot matrix printers",
        "look at acme dot com for details",
        "visit us at acme dot com",
        "available at shop dot example dot org today",
        "meet at the office",
        "the dot matrix printer arrives at noon",
        "nous regardons chez acme point matrice",
        "wir treffen uns at acme punkt eins",
        "llegamos a las nueve at the station dot",
        "arriviamo at the dot point",
    ],
)
def test_ordinary_prose_with_at_and_dot_words_is_untouched(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "jean at acme dot com",
        "write to jean.dupont at acme dot co dot uk today",
        "jean [at] acme [dot] com",
        "jean (at) acme (dot) com",
        "jean arobase acme point fr",
        "jean AT ACME DOT COM",
    ],
)
def test_obfuscated_addresses_are_still_removed(text: str) -> None:
    out = redact(text)

    assert "acme" not in out.lower()
    assert OMISSION in out


# --- lower-case names, from a clue only ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "gone", "kept"),
    [
        ("contact: jean dupont", ("jean", "dupont"), ("contact",)),
        ("m. dupont", ("dupont",), ("m.",)),
        ("signed by anna schmidt", ("anna", "schmidt"), ("signed by",)),
        ("ansprechpartner: hans meier", ("hans", "meier"), ("ansprechpartner",)),
        ("jean dupont, directeur achats", ("jean", "dupont"), ("directeur achats",)),
        ("anna schmidt, head of purchasing", ("anna", "schmidt"), ("head of purchasing",)),
        ("mme le gallic est absente", ("gallic",), ("mme", "absente")),
        ("firmado por remedios barrientos", ("remedios", "barrientos"), ("firmado por",)),
    ],
)
def test_a_lower_case_name_next_to_a_clue_is_redacted(
    text: str, gone: tuple[str, ...], kept: tuple[str, ...]
) -> None:
    out = redact(text)

    for item in gone:
        assert item not in out, out
    for item in kept:
        assert item in out, out


@pytest.mark.parametrize(
    "text",
    [
        "contact: our sales team",
        "contact: sales department",
        "head of purchasing",
        "contact: reception desk",
        "signé par voie électronique",
        "kind regards, sales team",
        "5 m. long and 3 m. wide",
    ],
)
def test_lower_case_prose_next_to_the_same_clues_is_untouched(text: str) -> None:
    assert redact(text) == text


def test_lower_case_names_with_a_clue_are_mostly_found_and_prose_is_left_alone() -> None:
    """Measured: 38/40 found, 0/41 prose lines altered. A lower-case name with no clue is not
    detected (a stated limit)."""
    redactor = _REAL[0]
    cases = lower_case_cases(8)
    found = sum(
        not any(part in redactor.redact(text).text.casefold() for part in parts)
        for _language, text, parts in cases
    )
    altered = [line for line in LOWER_PROSE if redactor.redact(line).text != line]

    assert found / len(cases) >= 0.9, (found, len(cases))
    assert len(altered) / len(LOWER_PROSE) <= 0.03, altered


def test_a_lower_case_name_with_no_clue_is_a_stated_limit() -> None:
    assert "dupont" in redact("we spoke to jean dupont about the order yesterday")
