"""The identity web search query keeps the supplier name through the real name detector."""

import pytest

from app.identity.agent import web_query_text
from app.redaction import RedactionContext, Redactor

pytestmark = pytest.mark.model


@pytest.mark.parametrize("name", ["Corvaglia", "Bossard", "Acme"])
def test_the_supplier_name_survives_redaction(real_redactor: Redactor, name: str) -> None:
    hints = {"website": "https://www.corvaglia.com/", "sector": "plastic closure manufacturer"}
    text = web_query_text(name, hints, "CH")

    redacted = real_redactor.redact(text, RedactionContext(keep=(name,))).text

    assert f'"{name}"' in redacted and "Switzerland (CH)" in redacted
