"""The supplier card as a PDF (spec F9, mock-up 06-pdf-card): data in, bytes out.

Safety rules of the renderer:
- every supplier and AI text goes through Jinja2 with autoescape on, as text, never as HTML;
- no URL derived from a supplier is ever fetched or linked: source addresses are printed as plain
  text, and the only resources the renderer may read are the local `tokens.css`, `fonts.css`,
  `pdf.css` and the font files of this folder (any other address fails the rendering);
- no model is called and nothing is stored: the bytes are returned to the caller.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from app.pdf.strings import STRINGS, Lang, format_date, format_datetime
from app.profile_definition import ProfileDefinition
from app.profile_routes import render as render_definition
from app.runs.routes import AssessmentOut, FactOut, RunOut

PDF_DIR = Path(__file__).resolve().parent
IAF_CERTSEARCH_URL = "https://www.iafcertsearch.org/"
REDACTION = "[…]"
# The kinds of statement, in the order the card lists them (SWOT and risks, gaps, fit, then the
# procurement recommendations).
SWOT_KINDS = ("strength", "weakness", "opportunity", "threat", "risk_indicator")
RECOMMENDATION_KINDS = (
    "procurement_implication",
    "relationship_level",
    "contract_approach",
    "volume_share",
    "next_action",
    "procurement_priority",
)
FIRST_EVALUATION = {
    "en": "Assuming a first evaluation of this supplier:",
    "fr": "En supposant une première évaluation de ce fournisseur :",
}
PRODUCER = "Supplier iScan"


class PdfUnavailable(RuntimeError):
    """The PDF library or its system libraries (Pango) are not available in this process."""


@dataclass(frozen=True)
class CardInput:
    run: RunOut
    facts: list[FactOut]
    definition: ProfileDefinition
    assessment: AssessmentOut
    buyer_inputs: Any  # BuyerInputsOut
    organisation_name: str
    generated_at: datetime
    lang: Lang
    disclaimer: str
    deletion_date: date | None = None


def _redacted(text: str | None) -> Markup:
    """Text with each redaction mark set apart, escaped like everything else."""
    parts = (text or "").split(REDACTION)
    # The parts are escaped here; the mark is our own markup.
    mark = Markup('<span class="redact">[…]</span>')  # noqa: S704
    return mark.join(escape(part) for part in parts)


def quote_language(text: str) -> str | None:
    """The language of a quote when its script tells it (the quote itself is never translated)."""
    if re.search(r"[぀-ヿ]", text):
        return "ja"
    if re.search(r"[가-힯]", text):
        return "ko"
    if re.search(r"[一-鿿]", text):
        return "zh"
    return None


_environment = Environment(
    loader=FileSystemLoader(PDF_DIR / "templates"),
    autoescape=select_autoescape(["html"], default=True),
    trim_blocks=True,
    lstrip_blocks=True,
)
_environment.filters["redacted"] = _redacted
_environment.filters["quote_language"] = quote_language


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _who(email: str | None, strings: dict[str, Any]) -> str:
    return email or strings["a_member"]


def _fact_block(
    fact: FactOut | None, field: Any, covered: bool, strings: dict[str, Any], lang: Lang
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "label": field.label,
        "people": field.concerns_people,
        "state": "fact",
    }
    if fact is None:
        block["state"] = "not_covered" if not covered else "not_examined"
        return block
    if fact.status == "not_found":
        block["state"] = "missing"
        if field.certification:
            block["verify"] = IAF_CERTSEARCH_URL
        return block
    quote = fact.quote or ""
    block.update(
        value=fact.value,
        status=fact.status,
        status_label=strings["status"][fact.status],
        quote=quote,
        quote_lang=quote_language(quote),
        redacted=fact.quote_redacted,
        source_type=strings["source_type"].get(fact.source_type or "", ""),
        source_line=(
            strings["found_in"].format(
                source=fact.publisher or fact.source_url or "",
                date=format_date(_utc(fact.fetched_at), lang) if fact.fetched_at else "",
            )
            if fact.quote
            else ""
        ),
        url=fact.source_url,
        original=fact.original_value if fact.status == "corrected" else None,
        verify=(fact.verification_url or IAF_CERTSEARCH_URL) if field.certification else None,
    )
    if fact.status != "proposed" and fact.reviewed_at:
        key = "approved_by" if fact.status == "approved" else "corrected_by"
        block["byline"] = strings[key].format(
            who=_who(fact.reviewed_by_email, strings),
            date=format_date(_utc(fact.reviewed_at), lang),
        )
    return block


def _statement(
    item: Any, fact_labels: dict[str, str], strings: dict[str, Any], lang: Lang
) -> dict[str, Any]:
    prov = item.provenance
    rules = prov.provider == "rules"
    when = format_datetime(_utc(prov.generated_at), lang)
    who = _who(prov.reviewed_by_email, strings)
    on = format_date(_utc(prov.reviewed_at), lang) if prov.reviewed_at else ""
    if prov.status == "ai_draft":
        review = strings["review_ai_draft"]
    else:
        review = strings[f"review_{prov.status}"].format(who=who, date=on)
    cites = [
        fact_labels[str(fact_id)] for fact_id in item.cited_fact_ids if str(fact_id) in fact_labels
    ]
    if item.cites_buyer_context and item.buyer_context_version:
        cites.append(strings["cites_buyer_context"].format(version=item.buyer_context_version))
    return {
        "kind": item.kind,
        "kind_label": strings["kinds"][item.kind],
        "text": item.text,
        "level": strings["levels"].get(item.level or ""),
        "relationship": strings["relationships"].get(item.label or ""),
        "timing": item.timing,
        "cites": cites,
        "gap_evidence": item.gap_evidence,
        "rules": rules,
        "badge": (
            None
            if rules
            else strings["ai_draft"]
            if prov.status == "ai_draft"
            else strings["status"].get(prov.status, prov.status)
        ),
        "decided": prov.status != "ai_draft",
        "byline": (
            strings["reviewed_by"].format(who=who, date=on) if prov.status != "ai_draft" else None
        ),
        "provenance": (
            strings["provenance_rules"].format(generated=when)
            if rules
            else strings["provenance_line"].format(
                provider=prov.provider,
                model=prov.model_id,
                version=prov.model_version,
                generated=when,
                review=review,
            )
        ),
        "outdated": item.buyer_context_outdated,
    }


def _financial(guidance: Any, strings: dict[str, Any]) -> dict[str, Any] | None:
    if guidance is None:
        return None
    return {
        "example": guidance.example_table,
        "configured": guidance.configured,
        "message": guidance.message,
        "caption": strings["fin_caption"].format(year=guidance.financial_year),
        "registry": guidance.registry_name,
        "registry_url": guidance.registry_url,
        "last_checked": guidance.last_checked,
        "documents": [
            {
                "type": strings["fin_types"].get(doc.type, doc.type),
                "scope": strings["fin_scopes"].get(doc.scope, doc.scope),
                "access": strings["fin_access_status"].get(doc.access, doc.access),
            }
            for doc in guidance.documents
        ],
        "missing": [strings["fin_missing_kinds"].get(k, k) for k in guidance.missing_evidence],
        "request": [strings["fin_request_kinds"].get(k, k) for k in guidance.documents_to_request],
    }


def build_context(card: CardInput) -> dict[str, Any]:
    lang = card.lang
    strings = STRINGS[lang]
    run = card.run
    definition = render_definition(card.definition, lang)
    by_field = {fact.field: fact for fact in card.facts}
    uncovered = set(run.uncovered_sections)
    partial = run.status == "partial"
    fact_labels = {
        str(fact.id): field.label
        for section in definition.sections
        for field in section.fields
        for fact in [by_field.get(field.id)]
        if fact is not None
    }
    section_labels = {section.id: section.label for section in definition.sections}
    sections = []
    total = missing = 0
    for section in definition.sections:
        fields = [field for field in section.fields if field.kind == "fact"]
        if not fields:
            continue
        blocks = []
        for field in fields:
            fact = by_field.get(field.id)
            covered = not (partial and section.id in uncovered)
            blocks.append(_fact_block(fact, field, covered, strings, lang))
            total += 1 if fact and fact.status != "not_found" else 0
            missing += 1 if fact and fact.status == "not_found" else 0
        sections.append(
            {
                "id": section.id,
                "label": section.label,
                "fields": blocks,
                "all_uncovered": partial
                and section.id in uncovered
                and not any(field.id in by_field for field in fields),
            }
        )
    proposed = sum(1 for fact in card.facts if fact.status == "proposed")

    assessment = card.assessment
    statements = [_statement(i, fact_labels, strings, lang) for i in assessment.items]
    groups = {
        "swot": [s for s in statements if s["kind"] in SWOT_KINDS],
        "gaps": [s for s in statements if s["kind"] == "evidence_gap"],
        "fit": [s for s in statements if s["kind"] == "fit"],
        "reco": [s for s in statements if s["kind"] in RECOMMENDATION_KINDS],
    }
    outdated = next((s for s in groups["reco"] if s["outdated"]), None)
    context_changed = None
    if outdated is not None:
        first = assessment.buyer_context_version is None
        context_changed = (
            strings["context_changed_first"]
            if first
            else strings["context_changed_body"].format(
                drafted=assessment.buyer_context_version or "-",
                current=assessment.current_buyer_context_version,
            )
        )
    inputs = card.buyer_inputs
    criteria = inputs.criteria
    context = inputs.buyer_context
    buyer_context = None
    if context is not None:
        when = format_date(_utc(context.updated_at), lang)
        buyer_context = {
            "note": strings["context_note"].format(
                who=_who(context.updated_by_email, strings), date=when, version=context.version
            ),
            "status": strings[
                "context_incumbent" if context.relationship == "incumbent" else "context_new"
            ],
            "share": None
            if context.current_share_pct is None
            else f"{context.current_share_pct:g} %",
            "end": None
            if context.contract_end_date is None
            else format_date(context.contract_end_date, lang),
            "intent": [strings["intents"].get(i, i) for i in context.strategic_intent],
            "notes": context.notes,
        }
    fit_criteria = None
    if criteria is not None and criteria.criteria:
        fit_criteria = {
            "title": strings["fit_criteria"].format(
                who=_who(criteria.updated_by_email, strings),
                date=format_date(_utc(criteria.updated_at), lang),
            ),
            "lines": criteria.criteria,
        }
    buyer_fields = {
        section_field.id: section_field.label
        for section in definition.sections
        for section_field in section.fields
        if section_field.kind == "buyer"
    }
    buyer_inputs = [
        {
            "label": buyer_fields.get(entry.field, entry.field),
            "text": entry.text,
            "note": strings["buyer_entered"].format(
                who=_who(entry.updated_by_email, strings),
                date=format_date(_utc(entry.updated_at), lang),
            ),
        }
        for entry in inputs.inputs
        if entry.text.strip()
    ]

    ai_rows = [
        {
            "kind": s["kind_label"],
            "provenance": item.provenance,
            "generated": format_datetime(_utc(item.provenance.generated_at), lang),
            "review": s["byline"] or strings["review_ai_draft"],
        }
        for s, item in zip(statements, assessment.items, strict=True)
        if not s["rules"]
    ]
    urls = sorted({fact.source_url for fact in card.facts if fact.source_url})

    # Provenance written to the file metadata: one entry per model/prompt/time, with its statements
    # counted by review status.
    provenance: dict[tuple[str, ...], dict[str, Any]] = {}
    for item in assessment.items:
        prov = item.provenance
        if prov.provider == "rules":
            continue
        key = (
            prov.provider,
            prov.model_id,
            prov.model_version,
            prov.prompt_id,
            prov.prompt_version,
        )
        entry = provenance.setdefault(
            key,
            {
                "provider": prov.provider,
                "model_id": prov.model_id,
                "model_version": prov.model_version,
                "prompt": f"{prov.prompt_id}@{prov.prompt_version}",
                "generated_at": _utc(prov.generated_at).isoformat(),
                "statements": {},
            },
        )
        entry["generated_at"] = max(entry["generated_at"], _utc(prov.generated_at).isoformat())
        entry["statements"][prov.status] = entry["statements"].get(prov.status, 0) + 1
    name = run.supplier_name or ""
    metadata = {
        "title": f"{strings['doc_title']} · {name}",
        "generator": PRODUCER,
        "created": _utc(card.generated_at).isoformat(),
        "lang": lang,
        "ai_generated_content": "true" if provenance else "false",
        "ai_provenance": json.dumps(
            list(provenance.values()), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ),
        "rules_guidance": "true" if any(s["rules"] for s in statements) else "false",
    }

    excluded = [source.domain for source in run.excluded_sources]
    generated = format_datetime(_utc(card.generated_at), lang)
    return {
        "lang": lang,
        "s": strings,
        "meta": metadata,
        "name": name,
        "organisation": card.organisation_name,
        "run": run,
        "website": run.supplier_website,
        "last_refresh": format_date(
            _utc(run.finished_at or run.started_at or run.created_at), lang
        ),
        "facts_summary": strings["facts_summary"].format(
            total=total + missing, proposed=proposed, missing=missing
        ),
        "generated": generated,
        "deleted_on": format_date(card.deletion_date, lang) if card.deletion_date else None,
        "disclaimer": card.disclaimer,
        "sections": sections,
        "partial": partial,
        "partial_sections": ", ".join(section_labels.get(i, i) for i in run.uncovered_sections),
        "identity_to_verify": run.identity_to_verify,
        "excluded": ", ".join(excluded),
        "natural_person": run.natural_person,
        "assessment_status": assessment.status,
        "groups": groups,
        "first_evaluation": FIRST_EVALUATION[lang],
        "context_changed": context_changed,
        "financial": _financial(assessment.financial_guidance, strings),
        "fit_criteria": fit_criteria,
        "buyer_context": buyer_context,
        "buyer_inputs": buyer_inputs,
        "ai_rows": ai_rows,
        "urls": urls,
        "run_ref": str(run.id),
        "footer": strings["footer"].format(generated=generated),
        "footer_deleted": (
            strings["footer_deleted"].format(date=format_date(card.deletion_date, lang))
            if card.deletion_date
            else None
        ),
        "css": {
            "tokens": "tokens.css",
            "fonts": "fonts.css",
            "pdf": "pdf.css",
        },
    }


def _fetcher() -> Any:
    """A fetcher that reads only the files of this folder: a remote or foreign address fails the
    rendering instead of being fetched."""
    from weasyprint.urls import URLFetcher

    root = PDF_DIR.resolve()

    class LocalOnly(URLFetcher):  # type: ignore[misc]
        def fetch(self, url: str, headers: Any = None) -> Any:
            if not url.startswith("file://"):
                raise ValueError("only local files are readable")
            path = Path(url.removeprefix("file://").split("?")[0]).resolve()
            if root not in path.parents:
                raise ValueError("only files of the PDF module are readable")
            return super().fetch(url, headers)

    return LocalOnly(allowed_protocols={"file"}, fail_on_errors=True)


_FACE = re.compile(r"@font-face\s*\{(.*?)\}", re.S)
_RANGE = re.compile(r"U\+([0-9A-Fa-f]+)(?:-([0-9A-Fa-f]+))?")
CJK_FAMILIES = {"ja": "IBM Plex Sans JP", "ko": "IBM Plex Sans KR", "zh": "IBM Plex Sans SC"}


@dataclass(frozen=True)
class _Face:
    family: str
    weight: int
    alias: str
    css: str
    ranges: tuple[tuple[int, int], ...]


@lru_cache(maxsize=1)
def _font_faces() -> tuple[_Face, ...]:
    """The @font-face rules of `fonts.css` (the copy of the web fonts' rules), parsed once.

    Each slice of a family gets a name of its own (`alias`). WeasyPrint identifies an embedded font
    by its description (family, weight, size), not by its file: two slices of the same family would
    be merged into one font and show the glyphs of the wrong file. Distinct names keep them apart.
    """
    faces = []
    for body in _FACE.findall((PDF_DIR / "fonts.css").read_text(encoding="utf-8")):
        family = re.search(r'font-family:\s*"([^"]+)"', body)
        weight = re.search(r"font-weight:\s*(\d+)", body)
        source = re.search(r'url\("([^"]+)"\)', body)
        match = re.search(r"unicode-range:\s*([^;]+);", body)
        if not (family and weight and source):
            continue
        alias = f"{family.group(1)} {Path(source.group(1)).stem}"
        ranges = (
            tuple((int(low, 16), int(high or low, 16)) for low, high in _RANGE.findall(match[1]))
            if match
            else ()
        )
        css = body.replace(f'"{family.group(1)}"', f'"{alias}"', 1)
        faces.append(
            _Face(family.group(1), int(weight.group(1)), alias, f"@font-face {{{css}}}", ranges)
        )
    return tuple(faces)


def font_css_for(text: str) -> str:
    """The @font-face rules for the font files that hold a character of the document, and the
    font stacks that use them. Loading all the IBM Plex slices (900 files, 21 MB) takes minutes; a
    French card needs a handful, and the CJK slices are loaded only when a quote contains such
    characters."""
    codes = {ord(character) for character in text}
    needed = [
        face
        for face in _font_faces()
        if not face.ranges
        or any(low <= code <= high for code in codes for low, high in face.ranges)
    ]

    def stack(family: str, weight: int) -> list[str]:
        return [
            f'"{face.alias}"' for face in needed if face.family == family and face.weight == weight
        ]

    cjk = {lang: stack(name, 400) for lang, name in CJK_FAMILIES.items()}
    fallback = [*cjk["ja"], *cjk["ko"], *cjk["zh"], "sans-serif"]
    stacks = {
        "sans-400": [*stack("IBM Plex Sans", 400), *fallback],
        "sans-500": [*stack("IBM Plex Sans", 500), *fallback],
        "sans-600": [*stack("IBM Plex Sans", 600), *fallback],
        "serif-400": [*stack("IBM Plex Serif", 400), *fallback],
        "serif-600": [*stack("IBM Plex Serif", 600), *fallback],
        "mono-400": [*stack("IBM Plex Mono", 400), *fallback],
    }
    for lang in CJK_FAMILIES:
        order = [lang, *(other for other in CJK_FAMILIES if other != lang)]
        stacks[lang] = [
            *(alias for other in order for alias in cjk[other]),
            *stack("IBM Plex Sans", 400),
            "sans-serif",
        ]
    variables = "\n".join(
        f"  --pdf-{name}: {', '.join(values)};" for name, values in stacks.items()
    )
    return "\n".join([*(face.css for face in needed), f":root {{\n{variables}\n}}"])


def render_html(card: CardInput) -> str:
    context = build_context(card)
    template = _environment.get_template("card.html")
    first = template.render(**context, font_faces="")
    # The font rules come from our own `fonts.css`, never from a supplier.
    faces = Markup(font_css_for(first))  # noqa: S704
    return template.render(**context, font_faces=faces)


def render_pdf(card: CardInput) -> bytes:
    try:
        from weasyprint import HTML
    except OSError as error:  # Pango or another system library is missing
        raise PdfUnavailable("The PDF library cannot load its system libraries.") from error
    html = render_html(card)
    document = HTML(string=html, base_url=PDF_DIR.as_uri() + "/", url_fetcher=_fetcher()).render()
    return bytes(document.write_pdf(custom_metadata=True))
