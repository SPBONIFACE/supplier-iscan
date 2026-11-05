"""The rules of the financial evidence guidance (spec, Financial evidence guidance; F8; #26).

Pure functions: no provider call, no network, no purchase. For the confirmed legal entity and a
financial year, each document gets exactly one access status:

- `registry_unavailable` when a request to the registry failed: never `no_filing_identified`, and
  never read as evidence that no filing exists;
- `no_filing_identified` when a lookup found no filing;
- otherwise the status of the country table (`public_download`, `free_registration`, `paid`,
  `reduced_disclosure`, `confidentiality_declared`).

A `paid`, `reduced_disclosure` or `registry_unavailable` document is described by what it is and
how to reach it, never as "unavailable". The supplier's own accounts are kept apart from
parent-company or consolidated accounts. The message names the missing evidence and the documents
to request from the supplier; where access is paid it links to the registry and buys nothing.
Commercial sources (credit scores, estimates, commercial reports) are a separate evidence class
and are never used here. An identity flagged `natural_person` gets no guidance at all.

What the lookups returned is an input (`Observations`): the MVP makes no automated registry lookup
(owner decision, 27 Oct 2026), so a run passes none, and the statuses come from the table.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final, Literal

from app.financial.table import DOCUMENT_TYPES, CountryRow, CountryTable

Outcome = Literal["found", "no_filing", "request_failed"]

STATUSES: Final = (
    "public_download",
    "free_registration",
    "paid",
    "reduced_disclosure",
    "confidentiality_declared",
    "no_filing_identified",
    "registry_unavailable",
)
DOCUMENTS_TO_REQUEST: Final = (
    "statutory_accounts",
    "audited_statements",
    "tax_schedules",
    "management_accounts",
)
# The evidence a buyer may still lack, in the order of the message.
EVIDENCE_OF: Final = {
    "income_statement": "income_statement",
    "notes": "full_notes",
    "audit_report": "audit_report",
}

GUIDANCE_PROVIDER: Final = "rules"
GUIDANCE_PROMPT_ID: Final = "financial_guidance"
GUIDANCE_VERSION: Final = "rules-1"

_TEXT: Final[dict[str, dict[str, Any]]] = {
    "en": {
        "document": {
            "income_statement": "income statement",
            "balance_sheet": "balance sheet",
            "notes": "notes to the accounts",
            "audit_report": "audit report",
        },
        "evidence": {
            "income_statement": "income statement",
            "full_notes": "full notes",
            "audit_report": "audit report",
            "more_recent_period": "a more recent period",
            "supplier_entity_accounts": "accounts of the supplier entity, not group accounts",
        },
        "request": {
            "statutory_accounts": "statutory accounts",
            "audited_statements": "audited statements",
            "tax_schedules": "tax schedules",
            "management_accounts": "management accounts",
        },
        "access": {
            "public_download": "can be downloaded from the registry",
            "free_registration": "can be obtained from the registry after a free registration",
            "paid": "is offered by the registry for a fee; this application buys no document",
            "reduced_disclosure": "may be filed in reduced form, with less detail",
            "confidentiality_declared": "may be covered by a declaration of confidentiality",
            "no_filing_identified": "no filing was identified by the registry lookup",
            "registry_unavailable": (
                "the registry could not be reached; this does not show that no filing exists"
            ),
        },
        "head": "Financial evidence for financial year {year}: no public evidence found "
        "among the collected sources.",
        "registry_line": "Registry: {name} ({url}), last checked {checked}{example}.",
        "example": "; example table, not verified",
        "unconfigured": "No registry guidance is configured for this country.",
        "group": "Only group or consolidated accounts were identified: they are kept apart "
        "from the supplier entity's own accounts.",
        "missing_line": "Evidence missing: {items}.",
        "request_line": "Documents to request from the supplier: {items}.",
        "scope_group": "group accounts",
        "closing": "No credit score, estimate or commercial report replaces filed financial "
        "statements.",
        "and": "; ",
    },
    "fr": {
        "document": {
            "income_statement": "compte de résultat",
            "balance_sheet": "bilan",
            "notes": "annexe des comptes",
            "audit_report": "rapport d'audit",
        },
        "evidence": {
            "income_statement": "compte de résultat",
            "full_notes": "annexe complète",
            "audit_report": "rapport d'audit",
            "more_recent_period": "une période plus récente",
            "supplier_entity_accounts": "comptes de l'entité fournisseur plutôt que comptes de "
            "groupe",
        },
        "request": {
            "statutory_accounts": "comptes annuels",
            "audited_statements": "états financiers audités",
            "tax_schedules": "liasses fiscales",
            "management_accounts": "comptes de gestion",
        },
        "access": {
            "public_download": "peut être téléchargé auprès du registre",
            "free_registration": "peut être obtenu auprès du registre après une inscription "
            "gratuite",
            "paid": "est proposé par le registre contre paiement ; cette application n'achète "
            "aucun document",
            "reduced_disclosure": "peut être déposé sous forme réduite, avec moins de détails",
            "confidentiality_declared": "peut faire l'objet d'une déclaration de confidentialité",
            "no_filing_identified": "aucun dépôt n'a été identifié par la recherche dans le "
            "registre",
            "registry_unavailable": (
                "le registre n'a pas pu être joint ; cela ne montre pas qu'aucun dépôt n'existe"
            ),
        },
        "head": "Éléments financiers pour l'exercice {year} : aucune preuve publique trouvée "
        "dans les sources collectées.",
        "registry_line": "Registre : {name} ({url}), dernière vérification le {checked}{example}.",
        "example": " ; table d'exemple, non vérifiée",
        "unconfigured": "Aucune indication de registre n'est configurée pour ce pays.",
        "group": "Seuls des comptes de groupe ou consolidés ont été identifiés : ils sont "
        "distingués des comptes propres de l'entité fournisseur.",
        "missing_line": "Éléments manquants : {items}.",
        "request_line": "Documents à demander au fournisseur : {items}.",
        "scope_group": "comptes de groupe",
        "closing": "Aucune note de crédit, estimation ou rapport commercial ne remplace les "
        "états financiers déposés.",
        "and": " ; ",
    },
}


@dataclass(frozen=True)
class Observations:
    """What lookups of the registry returned for this entity and year. Empty by default."""

    outcomes: Mapping[str, Outcome] = field(default_factory=dict)  # by document type
    group_accounts_only: bool = False
    latest_period: int | None = None  # the latest financial year with accounts collected
    collected: frozenset[str] = frozenset()  # document types already collected


@dataclass(frozen=True)
class Document:
    type: str
    scope: Literal["supplier_entity", "group"]
    access: str
    registry_link: str | None


@dataclass(frozen=True)
class Guidance:
    country: str | None
    financial_year: int
    configured: bool
    example_table: bool
    registry_name: str | None
    registry_url: str | None
    last_checked: str | None
    documents: tuple[Document, ...]
    missing_evidence: tuple[str, ...]
    documents_to_request: tuple[str, ...]
    message: str
    gap_evidence: str

    def to_json(self) -> dict[str, Any]:
        """The `FinancialGuidance` of openapi.yaml."""
        return {
            "country": self.country,
            "financial_year": self.financial_year,
            "configured": self.configured,
            "example_table": self.example_table,
            "registry_name": self.registry_name,
            "registry_url": self.registry_url,
            "last_checked": self.last_checked,
            "documents": [
                {
                    "type": item.type,
                    "scope": item.scope,
                    "access": item.access,
                    "registry_link": item.registry_link,
                }
                for item in self.documents
            ],
            "missing_evidence": list(self.missing_evidence),
            "documents_to_request": list(self.documents_to_request),
            "message": self.message,
        }


def financial_year(today: date) -> int:
    """The latest financial year that is over: accounts are filed after the year ends."""
    return today.year - 1


def access_status(table_status: str, outcome: Outcome | None) -> str:
    """The one status of a document. A failed request is `registry_unavailable`, never
    `no_filing_identified`; a lookup that found nothing is `no_filing_identified`."""
    if outcome == "request_failed":
        return "registry_unavailable"
    if outcome == "no_filing":
        return "no_filing_identified"
    return table_status


def _documents(row: CountryRow, observations: Observations) -> tuple[Document, ...]:
    documents = [
        Document(
            doc_type,
            "supplier_entity",
            access_status(row.access[doc_type], observations.outcomes.get(doc_type)),
            row.registry_url,
        )
        for doc_type in DOCUMENT_TYPES
    ]
    if observations.group_accounts_only:
        # Parent-company or consolidated accounts are a separate set, never the supplier's own.
        documents += [
            Document(
                doc_type,
                "group",
                access_status(row.access[doc_type], observations.outcomes.get(doc_type)),
                row.registry_url,
            )
            for doc_type in DOCUMENT_TYPES
            if doc_type in observations.outcomes
        ]
    return tuple(documents)


def _missing(year: int, observations: Observations) -> tuple[str, ...]:
    missing = [
        evidence
        for doc_type, evidence in EVIDENCE_OF.items()
        if doc_type not in observations.collected
    ]
    if observations.latest_period is not None and observations.latest_period < year:
        missing.append("more_recent_period")
    if observations.group_accounts_only:
        missing.append("supplier_entity_accounts")
    return tuple(missing)


def _join(items: list[str], language: str) -> str:
    separator: str = _TEXT[language]["and"]
    return separator.join(items)


def _message(
    language: str,
    year: int,
    row: CountryRow | None,
    example: bool,
    documents: tuple[Document, ...],
    missing: tuple[str, ...],
    observations: Observations,
) -> tuple[str, str]:
    text = _TEXT[language]
    parts = [text["head"].format(year=year)]
    if row is None:
        parts.append(text["unconfigured"])
    else:
        parts.append(
            text["registry_line"].format(
                name=row.registry_name,
                url=row.registry_url,
                checked=row.last_checked,
                example=text["example"] if example else "",
            )
        )
        lines = [
            f"{text['document'][item.type]}"
            f"{' (' + text['scope_group'] + ')' if item.scope == 'group' else ''}: "
            f"{text['access'][item.access]}"
            for item in documents
        ]
        parts.append(_join(lines, language) + ".")
    if observations.group_accounts_only:
        parts.append(text["group"])
    names = [text["evidence"][item] for item in missing]
    parts.append(text["missing_line"].format(items=_join(names, language)))
    requests = [text["request"][item] for item in DOCUMENTS_TO_REQUEST]
    parts.append(text["request_line"].format(items=_join(requests, language)))
    parts.append(text["closing"])
    return " ".join(parts), _join(names, language)


def build_guidance(
    table: CountryTable,
    country: str | None,
    language: str,
    year: int,
    natural_person: bool,
    observations: Observations | None = None,
) -> Guidance | None:
    """The guidance for the confirmed legal entity and `year`, or None when there is none to give:
    a natural-person business is not assessed, and nothing is missing when everything is
    collected."""
    if natural_person:
        return None
    observations = observations or Observations()
    language = language if language in _TEXT else "en"
    row = table.row(country)
    documents = _documents(row, observations) if row else ()
    missing = _missing(year, observations)
    if not missing:
        return None
    message, gap_evidence = _message(
        language, year, row, table.example, documents, missing, observations
    )
    return Guidance(
        country=(country or "").strip().upper() or None,
        financial_year=year,
        configured=row is not None,
        example_table=table.example,
        registry_name=row.registry_name if row else None,
        registry_url=row.registry_url if row else None,
        last_checked=row.last_checked if row else None,
        documents=documents,
        missing_evidence=missing,
        documents_to_request=DOCUMENTS_TO_REQUEST,
        message=message,
        gap_evidence=gap_evidence,
    )
