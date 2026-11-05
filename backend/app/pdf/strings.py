# ruff: noqa: E501 - label texts are kept on one line each, as in the locale files
"""Labels of the supplier card PDF in English and French (#39).

Wording follows the web card (frontend locales) and the approved mock-ups #6. French uses the
narrow no-break space (U+202F) before `:`, `;`, `?` and `!`. Supplier quotes and AI statements are
never translated: only these labels follow the requested language.
"""

from datetime import date, datetime
from typing import Literal

Lang = Literal["en", "fr"]
LANGS: tuple[Lang, ...] = ("en", "fr")
NNBSP = " "

_EN = {
    "doc_title": "Supplier profile",
    "kicker": "Supplier profile",
    "prepared_for": "Prepared for {organisation}",
    "identity": "Identity",
    "profile": "Profile",
    "legal_name": "Legal name",
    "website": "Website",
    "country": "Country",
    "sector": "Sector",
    "last_refresh": "Last refresh",
    "facts": "Facts",
    "facts_summary": "{total} facts · {proposed} still proposed · {missing} fields with no public evidence found",
    "source_content": "Source content",
    "deleted_on": "deleted on {date}",
    "generated": "Generated",
    "language": "Language",
    "language_value": "English · quotes in their source language",
    "run": "Run",
    "how_to_read": "How to read this brief",
    "legend_proposed": "Proposed by the AI, not yet reviewed by a member.",
    "legend_approved": "Accepted by a named member on a date. Not an independent verification.",
    "legend_supplier_claim": "The source is the supplier's own website or registry identity.",
    "legend_third_party": "The source is outside the supplier's domain and identifiers.",
    "legend_missing": "No verifiable quote was found. Not a negative statement.",
    "legend_ai_draft": "Assessment statement drafted by the AI, with its provenance.",
    "status": {"proposed": "Proposed", "approved": "Approved", "corrected": "Corrected"},
    "source_type": {
        "supplier_claim": "Supplier's own claim",
        "third_party": "Third-party source",
    },
    "redacted_extract": "Redacted extract",
    "found_in": "Found in {source} on {date}",
    "no_evidence": "No public evidence found",
    "not_covered_field": "Not covered by this run: it stopped before this field (partial).",
    "not_covered_section": "Not covered by this run: it stopped before this section (partial).",
    "not_examined": "Not examined by this run.",
    "original_value": "Original AI value:",
    "verify_iaf": "Verify on IAF CertSearch",
    "about_people": "About people: never used in the assessment",
    "approved_by": "Approved by {who} on {date}",
    "corrected_by": "Corrected by {who} on {date}",
    "a_member": "a member",
    "flag_partial": "partial",
    "flag_partial_body": (
        "This run stopped when it reached its cost budget. Sections not covered: {sections}. "
        "They were not examined, which says nothing about the supplier."
    ),
    "flag_identity": "identity to verify",
    "flag_identity_body": (
        "Nothing collected confirms the identity: the confirmed name “{name}” was not found in the "
        "content collected from the supplier's website, or the website gave no content. Check that "
        "this website belongs to the company you confirmed before relying on its facts."
    ),
    "flag_excluded": "source excluded at the site owner's request",
    "flag_excluded_body": "Not collected: {domains}.",
    "recommendations": "Procurement recommendations",
    "assessment": "Assessment",
    "assessment_lede": (
        "Drafted from the facts of this profile. Each statement cites the facts it relies on or "
        "names the evidence that is missing. There is no overall score."
    ),
    "assessment_partial": (
        "The run stopped when it reached its cost budget, so the assessment is incomplete. What is "
        "missing was not examined, which says nothing about the supplier."
    ),
    "assessment_pending": "The assessment was not drafted when this file was generated.",
    "not_assessed": "Not assessed: natural-person business",
    "not_assessed_note": "This says nothing about the supplier.",
    "ai_draft": "AI draft",
    "reviewed_by": "Reviewed by {who} on {date}",
    "cites": "Cites:",
    "cites_buyer_context": "Buyer context, version {version}",
    "level": "Level:",
    "relationship": "Relationship:",
    "timing": "Timing:",
    "context_changed": "Buyer context changed since this draft",
    "context_changed_body": (
        "Drafted with buyer context version {drafted}. Version {current} is stored now. The "
        "recommendations may no longer match it."
    ),
    "context_changed_first": (
        "Drafted on the first-evaluation assumption. A buyer context has been saved since. The "
        "recommendations may no longer match it."
    ),
    "provenance": "Provenance",
    "provenance_line": (
        "Provenance: {provider} · model {model} · version {version} · generated {generated} · "
        "review status: {review}"
    ),
    "provenance_rules": "Provenance: rules in code (no AI model) · generated {generated}",
    "review_ai_draft": "AI draft",
    "review_approved": "approved, reviewed by {who} on {date}",
    "review_corrected": "corrected, reviewed by {who} on {date}",
    "from_rules": "From the financial evidence guidance (rules in code and the country table). Not AI-generated.",
    "fin_title": "Financial evidence",
    "fin_example": "example table, not verified",
    "fin_example_body": (
        "The country rows behind this guidance come from the example table shipped with the "
        "product. They are placeholders and have not been verified: do not rely on them."
    ),
    "fin_not_configured": "No registry guidance is configured for this country.",
    "fin_caption": "Documents for financial year {year}",
    "fin_document": "Document",
    "fin_entity": "Entity",
    "fin_access": "Access status",
    "fin_missing": "Missing evidence",
    "fin_request": "Documents to request",
    "fin_registry": "Registry",
    "fin_last_checked": "Last checked",
    "fin_types": {
        "income_statement": "Income statement",
        "balance_sheet": "Balance sheet",
        "notes": "Notes to the accounts",
        "audit_report": "Audit report",
    },
    "fin_scopes": {
        "supplier_entity": "Supplier",
        "group": "Group (parent or consolidated accounts)",
    },
    "fin_access_status": {
        "public_download": "Public download",
        "free_registration": "Free with registration",
        "paid": "Paid access",
        "reduced_disclosure": "Reduced disclosure",
        "confidentiality_declared": "Confidentiality declared",
        "no_filing_identified": "No filing identified",
        "registry_unavailable": "Registry not reachable (this does not show that no filing exists)",
    },
    "fin_missing_kinds": {
        "income_statement": "Income statement",
        "full_notes": "Full notes",
        "audit_report": "Audit report",
        "more_recent_period": "A more recent period",
        "supplier_entity_accounts": "Supplier-entity accounts rather than group accounts",
    },
    "fin_request_kinds": {
        "statutory_accounts": "Statutory accounts",
        "audited_statements": "Audited statements",
        "tax_schedules": "Tax schedules",
        "management_accounts": "Management accounts",
    },
    "fit_title": "Fit against your criteria",
    "fit_criteria": "Fit criteria entered by {who} on {date}",
    "fit_empty": "Enter your criteria to assess fit",
    "context_title": "Buyer context",
    "context_note": "Entered by {who} on {date} (version {version}) · buyer input, not AI-generated",
    "context_incumbent": "Incumbent supplier",
    "context_new": "New supplier",
    "context_status": "Supplier status",
    "context_share": "Share of category spend",
    "context_end": "Contract end",
    "context_intent": "Strategic intent",
    "context_notes": "Notes",
    "intents": {
        "dual_sourcing": "Dual sourcing",
        "cost_reduction": "Cost reduction",
        "capacity_security": "Capacity security",
        "risk_reduction": "Risk reduction",
    },
    "buyer_inputs": "Buyer input",
    "buyer_inputs_note": "Written by members of your organisation. Not AI-generated.",
    "buyer_entered": "Entered by {who} on {date} · buyer input, not AI-generated",
    "kinds": {
        "strength": "Strength",
        "weakness": "Weakness",
        "opportunity": "Opportunity",
        "threat": "Threat",
        "risk_indicator": "Risk indicator",
        "evidence_gap": "Evidence gap",
        "fit": "Fit statement",
        "procurement_implication": "Overall procurement implication",
        "relationship_level": "Proposed relationship level",
        "contract_approach": "Contract approach",
        "volume_share": "Suggested volume share",
        "next_action": "Next action",
        "procurement_priority": "Procurement priority",
    },
    "levels": {"low": "low", "medium": "medium", "high": "high"},
    "relationships": {
        "strategic": "strategic",
        "preferred": "preferred",
        "transactional": "transactional",
    },
    "provenance_title": "Provenance and sources",
    "provenance_sources": "Sources",
    "statement": "Statement",
    "provider": "Provider",
    "model_id": "Model ID",
    "version": "Version",
    "generated_at": "Generated",
    "review": "Review",
    "reviewer": "Reviewer",
    "page": "Page {page} of {pages}",
    "footer": "Generated {generated}",
    "footer_deleted": "Source content deleted on {date}",
    "disclaimer_label": "Disclaimer",
}

_FR = {
    "doc_title": "Profil fournisseur",
    "kicker": "Profil fournisseur",
    "prepared_for": "Préparé pour {organisation}",
    "identity": "Identité",
    "profile": "Profil",
    "legal_name": "Raison sociale",
    "website": "Site web",
    "country": "Pays",
    "sector": "Secteur",
    "last_refresh": "Dernière actualisation",
    "facts": "Faits",
    "facts_summary": "{total} faits · {proposed} encore proposés · {missing} champs sans preuve publique trouvée",
    "source_content": "Contenu des sources",
    "deleted_on": "supprimé le {date}",
    "generated": "Généré",
    "language": "Langue",
    "language_value": "Français · citations dans leur langue d’origine",
    "run": "Analyse",
    "how_to_read": "Comment lire cette fiche",
    "legend_proposed": "Proposé par l’IA, pas encore relu par un membre.",
    "legend_approved": "Accepté par un membre nommé à une date. Ce n’est pas une vérification indépendante.",
    "legend_supplier_claim": "La source est le site du fournisseur ou son identité au registre.",
    "legend_third_party": "La source est extérieure au domaine et aux identifiants du fournisseur.",
    "legend_missing": "Aucune citation vérifiable n’a été trouvée. Ce n’est pas une affirmation négative.",
    "legend_ai_draft": "Affirmation de l’évaluation rédigée par l’IA, avec sa provenance.",
    "status": {"proposed": "Proposé", "approved": "Approuvé", "corrected": "Corrigé"},
    "source_type": {
        "supplier_claim": "Déclaration du fournisseur",
        "third_party": "Source tierce",
    },
    "redacted_extract": "Extrait masqué",
    "found_in": "Trouvé sur {source} le {date}",
    "no_evidence": "Aucune preuve publique trouvée",
    "not_covered_field": f"Non couvert par cette analyse{NNBSP}: elle s’est arrêtée avant ce champ (partiel).",
    "not_covered_section": f"Non couvert par cette analyse{NNBSP}: elle s’est arrêtée avant cette section (partiel).",
    "not_examined": "Non examiné par cette analyse.",
    "original_value": f"Valeur d’origine de l’IA{NNBSP}:",
    "verify_iaf": "Vérifier sur IAF CertSearch",
    "about_people": "Concerne des personnes : jamais utilisé dans l’évaluation".replace(
        " :", f"{NNBSP}:"
    ),
    "approved_by": "Approuvé par {who} le {date}",
    "corrected_by": "Corrigé par {who} le {date}",
    "a_member": "un membre",
    "flag_partial": "partiel",
    "flag_partial_body": (
        "Cette analyse s’est arrêtée en atteignant son budget de coût. Sections non couvertes"
        f"{NNBSP}: {{sections}}. Elles n’ont pas été examinées, ce qui ne dit rien du fournisseur."
    ),
    "flag_identity": "identité à vérifier",
    "flag_identity_body": (
        "Rien de ce qui a été collecté ne confirme l’identité : le nom confirmé « {name} » n’a pas "
        "été trouvé dans le contenu collecté sur le site du fournisseur, ou le site n’a donné aucun "
        "contenu. Vérifiez que ce site appartient bien à l’entreprise confirmée avant de vous "
        "fier à ses faits."
    ).replace(" :", f"{NNBSP}:"),
    "flag_excluded": "source exclue à la demande du propriétaire du site",
    "flag_excluded_body": "Non collectée : {domains}.".replace(" :", f"{NNBSP}:"),
    "recommendations": "Recommandations d’achat",
    "assessment": "Évaluation",
    "assessment_lede": (
        "Rédigée à partir des faits de ce profil. Chaque affirmation cite les faits sur lesquels "
        "elle s’appuie ou nomme l’information manquante. Il n’y a pas de note globale."
    ),
    "assessment_partial": (
        "L’analyse s’est arrêtée en atteignant son budget de coût : l’évaluation est incomplète. "
        "Ce qui manque n’a pas été examiné, ce qui ne dit rien du fournisseur."
    ).replace(" :", f"{NNBSP}:"),
    "assessment_pending": "L’évaluation n’était pas encore rédigée à la génération de ce fichier.",
    "not_assessed": f"Non évalué{NNBSP}: entreprise individuelle",
    "not_assessed_note": "Cela ne dit rien du fournisseur.",
    "ai_draft": "Brouillon IA",
    "reviewed_by": "Revu par {who} le {date}",
    "cites": f"S’appuie sur{NNBSP}:",
    "cites_buyer_context": "Contexte acheteur, version {version}",
    "level": f"Niveau{NNBSP}:",
    "relationship": f"Relation{NNBSP}:",
    "timing": f"Échéance{NNBSP}:",
    "context_changed": "Contexte acheteur modifié depuis ce brouillon",
    "context_changed_body": (
        "Rédigé avec la version {drafted} du contexte acheteur. La version {current} est "
        "enregistrée. Les recommandations peuvent ne plus correspondre."
    ),
    "context_changed_first": (
        "Rédigé en supposant une première évaluation. Un contexte acheteur a été enregistré "
        "depuis. Les recommandations peuvent ne plus correspondre."
    ),
    "provenance": "Provenance",
    "provenance_line": (
        f"Provenance{NNBSP}: {{provider}} · modèle {{model}} · version {{version}} · généré "
        f"{{generated}} · état de la revue{NNBSP}: {{review}}"
    ),
    "provenance_rules": f"Provenance{NNBSP}: règles du code (aucun modèle d’IA) · généré {{generated}}",
    "review_ai_draft": "brouillon IA",
    "review_approved": "approuvé, revu par {who} le {date}",
    "review_corrected": "corrigé, revu par {who} le {date}",
    "from_rules": "Issu des indications sur les éléments financiers (règles du code et table des pays). Non généré par l’IA.",
    "fin_title": "Éléments financiers",
    "fin_example": "table d’exemple, non vérifiée",
    "fin_example_body": (
        "Les lignes par pays à l’origine de ces indications viennent de la table d’exemple livrée "
        "avec le produit. Ce sont des valeurs provisoires, non vérifiées : ne vous y fiez pas."
    ).replace(" :", f"{NNBSP}:"),
    "fin_not_configured": "Aucune indication de registre n’est configurée pour ce pays.",
    "fin_caption": "Documents de l’exercice {year}",
    "fin_document": "Document",
    "fin_entity": "Entité",
    "fin_access": "Statut d’accès",
    "fin_missing": "Éléments manquants",
    "fin_request": "Documents à demander",
    "fin_registry": "Registre",
    "fin_last_checked": "Dernière vérification",
    "fin_types": {
        "income_statement": "Compte de résultat",
        "balance_sheet": "Bilan",
        "notes": "Annexes des comptes",
        "audit_report": "Rapport d’audit",
    },
    "fin_scopes": {
        "supplier_entity": "Fournisseur",
        "group": "Groupe (société mère ou comptes consolidés)",
    },
    "fin_access_status": {
        "public_download": "Téléchargement public",
        "free_registration": "Gratuit avec inscription",
        "paid": "Accès payant",
        "reduced_disclosure": "Publication réduite",
        "confidentiality_declared": "Confidentialité déclarée",
        "no_filing_identified": "Aucun dépôt identifié",
        "registry_unavailable": "Registre non joignable (cela ne montre pas qu’aucun dépôt n’existe)",
    },
    "fin_missing_kinds": {
        "income_statement": "Compte de résultat",
        "full_notes": "Annexes complètes",
        "audit_report": "Rapport d’audit",
        "more_recent_period": "Une période plus récente",
        "supplier_entity_accounts": "Comptes de l’entité fournisseur plutôt que du groupe",
    },
    "fin_request_kinds": {
        "statutory_accounts": "Comptes annuels",
        "audited_statements": "États financiers audités",
        "tax_schedules": "Liasses fiscales",
        "management_accounts": "Comptes de gestion",
    },
    "fit_title": "Adéquation avec vos critères",
    "fit_criteria": "Critères d’adéquation saisis par {who} le {date}",
    "fit_empty": "Saisissez vos critères pour évaluer l’adéquation",
    "context_title": "Contexte acheteur",
    "context_note": "Saisi par {who} le {date} (version {version}) · saisie de l’acheteur, non générée par l’IA",
    "context_incumbent": "Fournisseur en place",
    "context_new": "Nouveau fournisseur",
    "context_status": "Statut du fournisseur",
    "context_share": "Part des achats de la catégorie",
    "context_end": "Fin du contrat",
    "context_intent": "Intention stratégique",
    "context_notes": "Notes",
    "intents": {
        "dual_sourcing": "Double source",
        "cost_reduction": "Réduction des coûts",
        "capacity_security": "Sécurisation des capacités",
        "risk_reduction": "Réduction des risques",
    },
    "buyer_inputs": "Saisies de l’acheteur",
    "buyer_inputs_note": "Rédigées par des membres de votre organisation. Non générées par l’IA.",
    "buyer_entered": "Saisi par {who} le {date} · saisie de l’acheteur, non générée par l’IA",
    "kinds": {
        "strength": "Point fort",
        "weakness": "Point faible",
        "opportunity": "Opportunité",
        "threat": "Menace",
        "risk_indicator": "Indicateur de risque",
        "evidence_gap": "Information manquante",
        "fit": "Adéquation",
        "procurement_implication": "Implication globale pour les achats",
        "relationship_level": "Niveau de relation proposé",
        "contract_approach": "Approche contractuelle",
        "volume_share": "Part de volume suggérée",
        "next_action": "Prochaine action",
        "procurement_priority": "Priorité d’achat",
    },
    "levels": {"low": "faible", "medium": "moyen", "high": "élevé"},
    "relationships": {
        "strategic": "stratégique",
        "preferred": "privilégiée",
        "transactional": "transactionnelle",
    },
    "provenance_title": "Provenance et sources",
    "provenance_sources": "Sources",
    "statement": "Affirmation",
    "provider": "Fournisseur du modèle",
    "model_id": "Identifiant du modèle",
    "version": "Version",
    "generated_at": "Généré",
    "review": "Revue",
    "reviewer": "Relecteur",
    "page": "Page {page} sur {pages}",
    "footer": "Généré le {generated}",
    "footer_deleted": "Contenu des sources supprimé le {date}",
    "disclaimer_label": "Avertissement",
}

STRINGS: dict[Lang, dict] = {"en": _EN, "fr": _FR}  # type: ignore[type-arg]


def format_date(value: date | datetime, lang: Lang) -> str:
    """Oct 25, 2026 in English, 25/10/2026 in French (UTC), as on the screens."""
    if lang == "fr":
        return f"{value.day:02d}/{value.month:02d}/{value.year}"
    return f"{value.strftime('%b')} {value.day}, {value.year}"


def format_datetime(value: datetime, lang: Lang) -> str:
    """Date and time in UTC: "Nov 4, 2026, 18:00 UTC" or "04/11/2026 18:00 UTC"."""
    time = value.strftime("%H:%M")
    separator = " " if lang == "fr" else ", "
    return f"{format_date(value, lang)}{separator}{time} UTC"
