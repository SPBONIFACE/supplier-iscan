"""The AI disclosure is regulatory text: exact equality, French typography included."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.identity.strings import DISCLOSURE
from tests.auth_support import assert_requires_session, send_with_session
from tests.factories import create_session, create_user

# Spec F1, character for character: the no-break space (U+00A0) before the colon of the French
# text, the typographic apostrophes (U+2019), the accents.
ENGLISH = (
    "You are talking to an AI assistant. Its role: supplier research. As AI can make mistakes, "
    "please verify the legal entity of the selected supplier and the sources provided."
)
FRENCH = (
    "Vous échangez avec un assistant IA. Son rôle : effectuer des recherches fournisseur. "
    "L’IA pouvant faire des erreurs, veuillez vérifier l’entité légale du fournisseur "
    "sélectionné ainsi que les sources proposées."
)
SPEC = Path(__file__).resolve().parents[3] / "_docs" / "product" / "spec.md"


def test_the_texts_are_those_of_the_specification() -> None:
    assert DISCLOSURE["en"] == ENGLISH
    assert DISCLOSURE["fr"] == FRENCH
    assert " :" in DISCLOSURE["fr"] and DISCLOSURE["fr"].count("’") == 2


def test_the_texts_equal_the_ones_in_spec_f1() -> None:
    if not SPEC.exists():
        pytest.skip("the specification is not in this checkout")
    lines = SPEC.read_text(encoding="utf-8").splitlines()
    quoted = {
        language: re.search(r'"(.*)"', line).group(1)  # type: ignore[union-attr]
        for line in lines
        for language, label in (("en", "  - English: "), ("fr", "  - French: "))
        if line.startswith(label)
    }

    assert quoted == {"en": ENGLISH, "fr": FRENCH}


@pytest.mark.parametrize(("language", "expected"), [("en", ENGLISH), ("fr", FRENCH)])
def test_the_endpoint_returns_the_exact_text(
    client: TestClient, engine: Engine, language: str, expected: str
) -> None:
    token = create_session(engine, create_user(engine).id)

    response = send_with_session(client, "GET", f"/identity/disclosure?language={language}", token)

    assert response.status_code == 200
    assert response.json() == {"language": language, "text": expected}


def test_the_disclosure_needs_a_session_and_a_known_language(
    client: TestClient, engine: Engine
) -> None:
    assert_requires_session(client, engine, "GET", "/identity/disclosure?language=en")
    token = create_session(engine, create_user(engine).id)

    for path in ("/identity/disclosure?language=de", "/identity/disclosure"):
        assert send_with_session(client, "GET", path, token).status_code == 422
