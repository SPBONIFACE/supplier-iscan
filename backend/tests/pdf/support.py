"""Fixtures for the PDF tests (#39): a card built from the API models, no database."""

import io
import os
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from pypdf import PdfReader

from app.buyer.routes import BuyerInputsOut
from app.pdf.render import CardInput, PdfUnavailable, render_pdf
from app.pdf.strings import Lang
from app.profile_definition import load_profile_definition
from app.runs.routes import AssessmentOut, FactOut, RunOut

NOW = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
GENERATED_AT = datetime(2026, 10, 14, 9, 42, tzinfo=UTC)
RUN_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
DEFINITION = load_profile_definition()
DISCLAIMER = "[Disclaimer: to be supplied by the owner]"
CJK_QUOTE = "当社は東京に本社を置き、精密部品を製造しています。 我们在上海设有工厂。"
INJECTION = '<script>alert(1)</script><img src="http://169.254.169.254/latest/meta-data"></style>'


def run_out(**changes: Any) -> RunOut:
    values: dict[str, Any] = {
        "id": RUN_ID,
        "identity_id": uuid.uuid4(),
        "supplier_name": "Société Générale d’Œuvres Forgées",
        "supplier_website": "https://forge.example",
        "supplier_country": "France",
        "supplier_sector": "Forgeage de précision",
        "natural_person": False,
        "status": "completed",
        "stage": "assessment",
        "stop_requested": False,
        "counts_against_quota": True,
        "pause_dependency": None,
        "pause_reason": None,
        "error": None,
        "profile_definition_hash": None,
        "prompt_set_hash": None,
        "usage": {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "tool_calls": 0,
            "cost": "0",
            "roles": [],
        },
        "excluded_sources": [],
        "identity_to_verify": False,
        "grounding_failures": 0,
        "invalid_items": 0,
        "uncovered_sections": [],
        "partial_explanation": None,
        "proposed_facts": 0,
        "insufficient_sources_explanation": None,
        "created_at": datetime(2026, 10, 14, 9, 0, tzinfo=UTC),
        "started_at": datetime(2026, 10, 14, 9, 1, tzinfo=UTC),
        "finished_at": datetime(2026, 10, 14, 9, 40, tzinfo=UTC),
    }
    values.update(changes)
    return RunOut.model_validate(values)


def fact(field: str, section: str, **changes: Any) -> FactOut:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "section": section,
        "field": field,
        "status": "proposed",
        "value": f"Valeur de {field}",
        "quote": f"Citation d’origine pour {field}, très « précise ».",
        "quote_redacted": False,
        "source_id": uuid.uuid4(),
        "source_url": "https://forge.example/societe",
        "source_type": "supplier_claim",
        "publisher": "forge.example",
        "author": None,
        "fetched_at": datetime(2026, 10, 12, 8, 0, tzinfo=UTC),
        "verification_url": None,
        "original_value": None,
        "version": 1,
        "reviewed_by": None,
        "reviewed_by_email": None,
        "reviewed_at": None,
    }
    values.update(changes)
    return FactOut.model_validate(values)


def not_found(field: str, section: str) -> FactOut:
    return fact(
        field,
        section,
        status="not_found",
        value=None,
        quote=None,
        source_id=None,
        source_url=None,
        source_type=None,
        publisher=None,
        fetched_at=None,
    )


def statement(kind: str, text: str, **changes: Any) -> dict[str, Any]:
    provenance = {
        "provider": "google",
        "model_id": "gemini-flash-eu-01",
        "model_version": "2026-09",
        "prompt_id": "assessment",
        "prompt_version": "3",
        "generated_at": GENERATED_AT,
        "status": "ai_draft",
        "reviewed_by": None,
        "reviewed_by_email": None,
        "reviewed_at": None,
    }
    provenance.update(changes.pop("provenance", {}))
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "kind": kind,
        "text": text,
        "level": None,
        "label": None,
        "timing": None,
        "cited_fact_ids": [],
        "cites_buyer_context": False,
        "gap_evidence": None,
        "buyer_context_version": None,
        "buyer_context_outdated": False,
        "provenance": provenance,
        "version": 1,
        "original_text": None,
    }
    values.update(changes)
    return values


def assessment(items: list[dict[str, Any]], **changes: Any) -> AssessmentOut:
    values: dict[str, Any] = {
        "status": "drafted",
        "message": None,
        "buyer_context_version": None,
        "current_buyer_context_version": None,
        "fit_message": None,
        "pending": [],
        "financial_guidance": None,
        "rejected_statements": 0,
        "items": items,
    }
    values.update(changes)
    return AssessmentOut.model_validate(values)


def buyer_inputs(**changes: Any) -> BuyerInputsOut:
    values: dict[str, Any] = {"criteria": None, "buyer_context": None, "inputs": []}
    values.update(changes)
    return BuyerInputsOut.model_validate(values)


def all_facts(**overrides: Any) -> list[FactOut]:
    """One fact per `fact` field of the definition: a mix of statuses, a gap, a CJK quote."""
    facts = []
    for section in DEFINITION.sections:
        for index, field in enumerate(section.fields):
            if field.kind != "fact":
                continue
            if index == 1:
                facts.append(not_found(field.id, section.id))
            else:
                facts.append(fact(field.id, section.id, **overrides))
    return facts


def card(lang: Lang = "en", **changes: Any) -> CardInput:
    facts = changes.pop("facts", None) or all_facts()
    cited = [facts[0].id]
    values: dict[str, Any] = {
        "run": run_out(),
        "facts": facts,
        "definition": DEFINITION,
        "assessment": assessment(
            [
                statement("strength", "Deux sites certifiés ISO 9001.", cited_fact_ids=cited),
                statement(
                    "weakness",
                    "Une seule certification automobile.",
                    cited_fact_ids=cited,
                    provenance={
                        "status": "approved",
                        "reviewed_by_email": "claire@example.org",
                        "reviewed_at": datetime(2026, 10, 16, 8, 0, tzinfo=UTC),
                    },
                ),
                statement(
                    "relationship_level",
                    "Assuming a first evaluation of this supplier: keep a preferred relationship.",
                    label="preferred",
                    cited_fact_ids=cited,
                ),
                statement("next_action", "Request the IATF certificate.", timing="30 days"),
            ]
        ),
        "buyer_inputs": buyer_inputs(),
        "organisation_name": "Atelier Nord Industrie",
        "generated_at": NOW,
        "lang": lang,
        "disclaimer": DISCLAIMER,
        "deletion_date": date(2027, 1, 12),
    }
    values.update(changes)
    return CardInput(**values)


def pdf_or_skip(input_: CardInput) -> bytes:
    """The rendered file; skipped where Pango is missing (a developer's laptop), failed in CI."""
    try:
        return render_pdf(input_)
    except PdfUnavailable:
        if os.environ.get("CI"):
            pytest.fail("WeasyPrint's system libraries (Pango) must be installed in CI")
        pytest.skip("WeasyPrint's system libraries (Pango) are not installed here")


def text_of(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() for page in reader.pages)


def flat_text_of(content: bytes) -> str:
    """The extracted text with space variants and line breaks folded into single spaces."""
    text = text_of(content).replace(" ", " ").replace(" ", " ")
    return " ".join(text.split())


def metadata_of(content: bytes) -> dict[str, str]:
    info = PdfReader(io.BytesIO(content)).metadata
    assert info is not None
    return {str(key): str(value) for key, value in info.items()}


def font_names(content: bytes) -> set[str]:
    names: set[str] = set()
    for page in PdfReader(io.BytesIO(content)).pages:
        resources: Any = page["/Resources"]
        for font in (resources.get("/Font") or {}).values():
            names.add(str(font.get_object().get("/BaseFont", "")))
    return names
