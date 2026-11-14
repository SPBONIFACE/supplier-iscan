"""The collection and extraction supplier lines keep the supplier name through the real detector.

Unquoted, "Legal name: Corvaglia" followed by the website line became "Legal name: […]: https://...":
the web search of collection ran without the supplier's name (dev run of 14 Nov 2026).
"""

import pytest

from app.collection.retrieval import IdentityRecord, _supplier_text
from app.extraction.stage import Supplier
from app.redaction import RedactionContext, Redactor

pytestmark = pytest.mark.model

WEBSITE = "https://www.corvaglia.com/"


@pytest.mark.parametrize("name", ["Corvaglia", "Bossard", "Acme Supplies SA"])
def test_the_collection_query_keeps_the_supplier_name(real_redactor: Redactor, name: str) -> None:
    text = _supplier_text(IdentityRecord(name, WEBSITE, "CH"), ["financials"])

    redacted = real_redactor.redact(text, RedactionContext(keep=(name,))).text

    assert f'Legal name: "{name}"' in redacted and f"Website: {WEBSITE}" in redacted


@pytest.mark.parametrize("name", ["Corvaglia", "Bossard"])
def test_the_extraction_supplier_lines_keep_the_supplier_name(
    real_redactor: Redactor, name: str
) -> None:
    text = Supplier(name=name, website=WEBSITE, country="CH").text()

    redacted = real_redactor.redact(text, RedactionContext(keep=(name,))).text

    assert f'Legal name: "{name}"' in redacted and f"Website: {WEBSITE}" in redacted
