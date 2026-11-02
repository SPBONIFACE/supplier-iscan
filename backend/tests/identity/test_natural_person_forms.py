"""The natural-person flag: sole-trader forms are caught, company forms are not."""

import pytest

from app.identity.candidates import is_natural_person

NATURAL = [
    "Micro-entreprise",
    "micro entrepreneur",
    "Auto-entrepreneur",
    "EI",
    "E.I.",
    "e.i.",
    "Entreprise individuelle",
    "Entrepreneur individuel",
    "EIRL",
    "e.K.",
    "eK",
    "e. K.",
    "E.K",
    "Einzelunternehmer",
    "Einzelunternehmen",
    "Einzelfirma",
    "Einzelkaufmann",
    "Eingetragener Kaufmann",
    "Sole-trader",
    "Sole trader",
    "Sole Proprietor",
    "Individual proprietorship",
    "Individual proprietor",
    "Selbstständiger",
    "SELBSTSTÄNDIGER",
    "Travailleur indépendant",
    "Libero professionista",
    "Self-employed",
    "Persona física",
    "Autónomo",
    "Ditta individuale",
    "Eenmanszaak",
    "DBA",
    "d/b/a",
    "Doing business as",
    "Freiberufler",
    "Natural person",
]
COMPANY = [
    "SAS",
    "SARL",
    "GmbH",
    "Ltd",
    "LLC",
    "Inc.",
    "S.L.",
    "S.r.l.",
    "AG",
    "KG",
    "BV",
    "PLC",
    "SCI",
    "SA",
    "Reinhardt GmbH",
    "Weil AG",
    "Ei Electronics Ltd",
    "EIRL Holding SAS",
    "Einstein GmbH & Co. KG",
    "Deicke GmbH",
    "Dbase Ltd",
    "Meek Inc.",
    "",
    None,
]


@pytest.mark.parametrize("label", NATURAL)
def test_natural_person_forms_are_flagged(label: str | None) -> None:
    assert is_natural_person(label) is True


@pytest.mark.parametrize("label", COMPANY)
def test_company_forms_are_not_flagged(label: str | None) -> None:
    assert is_natural_person(label) is False
