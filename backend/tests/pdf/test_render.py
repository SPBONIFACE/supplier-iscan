"""The supplier card PDF (#39): content, language, provenance, escaping, no remote fetch."""

import html as htmllib
import io
import json
import socket
from typing import Any

import pytest
from pypdf import PdfReader

from app.pdf.render import PDF_DIR, _fetcher, render_html
from tests.pdf.support import (
    CJK_QUOTE,
    DEFINITION,
    DISCLAIMER,
    GENERATED_AT,
    INJECTION,
    all_facts,
    assessment,
    buyer_inputs,
    card,
    fact,
    font_names,
    metadata_of,
    pdf_or_skip,
    run_out,
    statement,
    text_of,
)


def flat(text: str) -> str:
    """Extracted text with every space variant folded, so that line breaks do not matter."""
    return " ".join(text.replace(" ", " ").replace(" ", " ").split())


def has(text: str, expected: str) -> bool:
    """Case-insensitive: micro labels and badges are set in capitals, which the text keeps."""
    return expected.lower() in text.lower()


def test_the_card_has_every_fact_the_assessment_the_flags_and_the_footer_in_english() -> None:
    facts = [f for f in all_facts() if f.section != "certifications"]  # not examined (partial)
    facts[0] = fact(
        facts[0].field,
        facts[0].section,
        status="corrected",
        value="480 (2025)",
        original_value="450 (2023)",
        quote="Le forgeron, qui emploie 480 personnes, selon […], son directeur.",
        quote_redacted=True,
        source_type="third_party",
        reviewed_by_email="claire@example.org",
        reviewed_at=GENERATED_AT,
    )
    content = pdf_or_skip(
        card(
            "en",
            facts=facts,
            run=run_out(
                status="partial", uncovered_sections=["certifications"], identity_to_verify=True
            ),
        )
    )
    text = flat(text_of(content))

    assert has(text, "Supplier profile") and has(text, "Prepared for Atelier Nord Industrie")
    assert has(text, "480 (2025)") and has(text, "Original AI value: 450 (2023)")
    assert has(text, "Le forgeron, qui emploie 480 personnes, selon […], son directeur.")
    assert has(text, "Redacted extract") and has(text, "Third-party source")
    assert has(text, "Corrected by claire@example.org on Oct 14, 2026")
    assert has(text, "Found in forge.example on Oct 12, 2026")
    assert has(text, "https://forge.example/societe")
    assert has(text, "No public evidence found")
    assert has(text, "Not covered by this run")  # partial: the certifications were not examined
    assert has(text, "identity to verify") and has(text, "partial")
    assert has(text, "AI draft") and has(text, "Approved")
    assert has(text, "Reviewed by claire@example.org on Oct 16, 2026")
    assert has(text, "Provenance: google · model gemini-flash-eu-01 · version 2026-09")
    assert has(text, DISCLAIMER)
    assert has(text, "Generated Nov 5, 2026, 09:30 UTC")
    assert has(text, "Source content deleted on Jan 12, 2027")
    assert has(text, "Page 1 of")
    assert len(PdfReader(io.BytesIO(content)).pages) >= 2


def test_the_french_card_has_french_labels_accents_and_a_cjk_quote() -> None:
    facts = all_facts()
    facts[1] = fact(facts[1].field, facts[1].section, quote=CJK_QUOTE, value="東京")
    content = pdf_or_skip(card("fr", facts=facts))
    text = flat(text_of(content))

    assert has(text, "Profil fournisseur") and has(text, "Préparé pour Atelier Nord Industrie")
    assert has(text, "Société Générale d’Œuvres Forgées")
    assert has(text, "Aucune preuve publique trouvée")
    assert has(text, "Brouillon IA") and has(text, "Revu par claire@example.org le 16/10/2026")
    assert has(text, "Généré le 05/11/2026 09:30 UTC")
    assert has(text, "Contenu des sources supprimé le 12/01/2027")
    assert has(text, "Page 1 sur")
    assert has(text, "Citation d’origine pour")  # quotes stay in their source language
    compact = text.replace(" ", "")  # extraction may add a space between runs of CJK glyphs
    assert "東京" in compact and "精密部品" in compact and "我们在上海设有工厂" in compact
    assert has(text, DISCLAIMER)
    names = font_names(content)
    assert any("IBMPlexSans" in name for name in names), names
    assert any("JP" in name or "SC" in name for name in names), names  # CJK glyphs embedded


def test_the_provenance_is_written_to_the_file_metadata_and_read_back() -> None:
    content = pdf_or_skip(card("en"))
    info = metadata_of(content)

    assert info["/Title"] == "Supplier profile · Société Générale d’Œuvres Forgées"
    assert info["/aigeneratedcontent"] == "true"
    provenance: list[dict[str, Any]] = json.loads(info["/aiprovenance"])
    assert provenance == [
        {
            "generated_at": "2026-10-14T09:42:00+00:00",
            "model_id": "gemini-flash-eu-01",
            "model_version": "2026-09",
            "prompt": "assessment@3",
            "provider": "google",
            "statements": {"ai_draft": 3, "approved": 1},
        }
    ]
    assert info["/contentlanguage"] == "en"
    assert info["/rulesguidance"] == "false"


def test_a_natural_person_is_not_assessed_and_has_no_recommendation() -> None:
    content = pdf_or_skip(
        card(
            "en",
            run=run_out(natural_person=True),
            assessment=assessment([]),
        )
    )
    text = flat(text_of(content))

    assert has(text, "Not assessed: natural-person business")
    assert not has(text, "Procurement recommendations")
    assert not has(text, "Strength")
    assert metadata_of(content)["/aigeneratedcontent"] == "false"


def test_rules_guidance_shows_the_provenance_rules_and_the_recommendation_blocks() -> None:
    items = [
        statement(
            "evidence_gap",
            "Supplier-entity accounts are not public.",
            gap_evidence="Request the statutory accounts.",
            provenance={"provider": "rules", "model_id": "rules", "model_version": "1"},
        ),
        statement(
            "relationship_level",
            "Assuming a first evaluation of this supplier: strategic.",
            label="strategic",
            level="high",
            buyer_context_outdated=True,
        ),
    ]
    guidance = {
        "country": "France",
        "financial_year": 2025,
        "configured": True,
        "example_table": True,
        "registry_name": "Registry",
        "registry_url": "https://registry.example/fr",
        "last_checked": "2026-10-01",
        "documents": [
            {
                "type": "balance_sheet",
                "scope": "supplier_entity",
                "access": "confidentiality_declared",
                "registry_link": None,
            }
        ],
        "missing_evidence": ["audit_report"],
        "documents_to_request": ["statutory_accounts"],
        "message": "Financial statements for FY 2025.",
    }
    content = pdf_or_skip(
        card(
            "en",
            assessment=assessment(
                items, financial_guidance=guidance, current_buyer_context_version=2
            ),
        )
    )
    text = flat(text_of(content))

    assert has(text, "Provenance: rules in code (no AI model)")
    assert has(text, "Not AI-generated")
    assert has(text, "example table, not verified") and has(text, "Confidentiality declared")
    assert has(text, "Proposed relationship level") and has(text, "Relationship: strategic")
    assert has(text, "Buyer context changed since this draft")
    assert has(text, "Assuming a first evaluation of this supplier")
    assert metadata_of(content)["/rulesguidance"] == "true"


def test_buyer_context_and_inputs_appear_as_entered() -> None:
    inputs = buyer_inputs(
        criteria={
            "criteria": ["IATF 16949 required"],
            "version": 1,
            "updated_by": None,
            "updated_by_email": "claire@example.org",
            "updated_at": GENERATED_AT,
        },
        buyer_context={
            "relationship": "incumbent",
            "current_share_pct": 12,
            "contract_end_date": "2027-06-30",
            "strategic_intent": ["dual_sourcing"],
            "notes": "Second source under way.",
            "version": 2,
            "updated_by": None,
            "updated_by_email": "claire@example.org",
            "updated_at": GENERATED_AT,
        },
        inputs=[
            {
                "field": "buyer_notes",
                "text": "Visited the site in May.",
                "version": 1,
                "updated_by": None,
                "updated_by_email": "claire@example.org",
                "updated_at": GENERATED_AT,
            }
        ],
    )
    text = flat(text_of(pdf_or_skip(card("en", buyer_inputs=inputs))))

    assert has(text, "IATF 16949 required") and has(text, "Incumbent supplier")
    assert has(text, "12 %") and has(text, "Jun 30, 2027") and has(text, "Dual sourcing")
    assert has(text, "Visited the site in May.") and has(text, "not AI-generated")


def test_a_long_profile_breaks_across_pages_and_every_page_has_the_footer() -> None:
    long_quote = " ".join(["Une très longue citation de la source, mot après mot."] * 6)[:300]
    facts = all_facts(quote=long_quote)
    items = [statement("strength", f"Statement {i} " + "word " * 60) for i in range(25)]
    content = pdf_or_skip(card("en", facts=facts, assessment=assessment(items)))
    reader = PdfReader(io.BytesIO(content))

    assert len(reader.pages) >= 4
    for page in reader.pages:
        assert DISCLAIMER in flat(page.extract_text())


def test_supplier_and_ai_text_is_escaped_and_nothing_remote_is_fetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = all_facts()
    facts[0] = fact(
        facts[0].field,
        facts[0].section,
        value=INJECTION,
        quote=INJECTION,
        source_url="http://169.254.169.254/latest/meta-data",
    )
    input_ = card(
        "en",
        facts=facts,
        run=run_out(supplier_name=INJECTION, supplier_website="http://127.0.0.1:1/x"),
        assessment=assessment([statement("strength", INJECTION)]),
    )
    html = render_html(input_)

    assert "<script>" not in html and "<img" not in html and "&lt;script&gt;" in html
    assert "href=" not in html.split("</head>")[1]  # no supplier address is a link

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a network connection was attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    text = flat(text_of(pdf_or_skip(input_)))
    assert has(text, "<script>alert(1)</script>")  # printed as text


def test_the_renderer_reads_only_the_files_of_its_own_folder() -> None:
    pytest.importorskip("weasyprint")
    try:
        fetcher = _fetcher()
    except OSError:
        pytest.skip("WeasyPrint's system libraries are not installed here")
    for url in (
        "http://example.test/x.css",
        "https://example.test/x.png",
        "ftp://example.test/x",
        "data:text/plain,hello",
        "file:///etc/passwd",
        (PDF_DIR / ".." / "config.py").resolve().as_uri(),
    ):
        with pytest.raises(ValueError):
            fetcher.fetch(url)
    assert fetcher.fetch((PDF_DIR / "pdf.css").as_uri()) is not None


def test_the_definition_labels_follow_the_requested_language() -> None:
    english = htmllib.unescape(render_html(card("en")))
    french = htmllib.unescape(render_html(card("fr")))

    first = DEFINITION.sections[0]
    assert first.labels["en"] in english and first.labels["fr"] in french
    assert first.labels["fr"] not in english and first.labels["en"] not in french


def test_an_unexamined_field_never_reads_as_no_public_evidence() -> None:
    facts = [f for f in all_facts() if f.section != "certifications"]
    text = render_html(
        card(
            "en", facts=facts, run=run_out(status="partial", uncovered_sections=["certifications"])
        )
    )
    section = text.split("Certifications</h2>", 1)[1].split('<section class="assessment">')[0]

    assert "Not covered by this run" in section
    assert "No public evidence found" not in section
