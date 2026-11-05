// Fixtures for the tests of the supplier card: a run, a profile definition, facts. Shared by the tests
// of the review (#36) and of the assessment section (#37).
import type {
  Assessment,
  AssessmentStatement,
  BuyerContext,
  BuyerInputs,
  Fact,
  FinancialGuidance,
  ProfileDefinition,
  Run,
} from "../lib/api";

export const RUN_ID = "44444444-4444-4444-8444-444444444444";
export const CARD_PATH = `/profiles/${RUN_ID}`;

export const makeRun = (changes: Partial<Run> = {}): Run =>
  ({
    id: RUN_ID,
    identity_id: "55555555-5555-4555-8555-555555555555",
    supplier_name: "Corvane Précision SAS",
    supplier_website: "https://corvane-precision.example/",
    supplier_country: "France",
    supplier_sector: "Precision machining for aerospace",
    natural_person: false,
    status: "completed",
    stage: "assessment",
    identity_to_verify: false,
    excluded_sources: [],
    stop_requested: false,
    proposed_facts: 3,
    uncovered_sections: [],
    created_at: "2026-10-26T10:00:00Z",
    started_at: "2026-10-26T10:00:30Z",
    finished_at: "2026-10-26T10:20:00Z",
    ...changes,
  }) as Run;

type Field = ProfileDefinition["sections"][number]["fields"][number];

export const makeField = (id: string, label: string, extra: Partial<Field> = {}): Field => ({
  id,
  label,
  kind: "fact",
  certification: false,
  concerns_people: false,
  key_figure: false,
  ...extra,
});

export const makeDefinition = (language: "en" | "fr" = "en"): ProfileDefinition => {
  const fr = language === "fr";
  return {
    hash: "sha256:x",
    language,
    sections: [
      {
        id: "company_overview",
        label: fr ? "Présentation de l’entreprise" : "Company overview",
        fields: [
          makeField("legal_form", fr ? "Forme juridique" : "Legal form"),
          makeField("founding_year", fr ? "Année de création" : "Founding year"),
          makeField("employee_count", fr ? "Nombre de salariés" : "Number of employees"),
        ],
      },
      {
        id: "certifications",
        label: "Certifications",
        fields: [
          makeField("quality_management", fr ? "Management de la qualité" : "Quality management"),
          makeField("environmental_management", "Environmental management"),
        ],
      },
      {
        id: "buyer",
        label: fr ? "Votre avis" : "Your notes",
        fields: [
          makeField("buyer_notes", fr ? "Notes de l’acheteur" : "Buyer notes", { kind: "buyer" }),
          makeField("buyer_history", fr ? "Historique commercial" : "Commercial history", {
            kind: "buyer",
          }),
        ],
      },
    ],
  };
};

export const makeFact = (fieldId: string, section: string, changes: Partial<Fact> = {}): Fact => ({
  id: `fact-${fieldId}`,
  section,
  field: fieldId,
  status: "proposed",
  value: `Value of ${fieldId}`,
  quote: `Quote for ${fieldId}`,
  quote_redacted: false,
  source_id: "77777777-7777-4777-8777-777777777777",
  source_url: "https://corvane-precision.example/about",
  source_type: "supplier_claim",
  publisher: "corvane-precision.example",
  author: null,
  fetched_at: "2026-10-26T10:05:00Z",
  verification_url: null,
  original_value: null,
  version: 1,
  reviewed_by: null,
  reviewed_by_email: null,
  reviewed_at: null,
  ...changes,
});

export const makeNotFound = (fieldId: string, section: string): Fact =>
  makeFact(fieldId, section, {
    status: "not_found",
    value: null,
    quote: null,
    source_id: null,
    source_url: null,
    source_type: null,
    publisher: null,
    fetched_at: null,
  });

export const makeStatement = (
  id: string,
  kind: AssessmentStatement["kind"],
  text: string,
  changes: Partial<AssessmentStatement> = {},
  provenance: Partial<AssessmentStatement["provenance"]> = {},
): AssessmentStatement => ({
  id,
  version: 1,
  original_text: null,
  kind,
  text,
  level: null,
  label: null,
  timing: null,
  cited_fact_ids: [],
  cites_buyer_context: false,
  gap_evidence: null,
  buyer_context_version: null,
  buyer_context_outdated: false,
  provenance: {
    provider: "google",
    model_id: "gemini-flash-sample",
    model_version: "2026-09",
    prompt_id: "assessment",
    prompt_version: "1",
    generated_at: "2026-10-26T16:04:00Z",
    status: "ai_draft",
    reviewed_by: null,
    reviewed_by_email: null,
    reviewed_at: null,
    ...provenance,
  },
  ...changes,
});

export const makeGuidance = (changes: Partial<FinancialGuidance> = {}): FinancialGuidance => ({
  country: "France",
  financial_year: 2025,
  configured: true,
  example_table: false,
  registry_name: "National companies registry (example)",
  registry_url: "https://registry.example/fr",
  last_checked: "2026-10-01",
  documents: [
    {
      type: "balance_sheet",
      scope: "supplier_entity",
      access: "free_registration",
      registry_link: null,
    },
    {
      type: "income_statement",
      scope: "supplier_entity",
      access: "confidentiality_declared",
      registry_link: null,
    },
    {
      type: "audit_report",
      scope: "supplier_entity",
      access: "no_filing_identified",
      registry_link: null,
    },
    {
      type: "balance_sheet",
      scope: "group",
      access: "paid",
      registry_link: "https://registry.example/fr/group",
    },
  ],
  missing_evidence: ["income_statement", "audit_report", "supplier_entity_accounts"],
  documents_to_request: ["statutory_accounts", "audited_statements"],
  message: "Financial statements for Corvane Précision SAS, financial year 2025.",
  ...changes,
});

export const makeAssessment = (changes: Partial<Assessment> = {}): Assessment => ({
  status: "drafted",
  message: null,
  buyer_context_version: null,
  current_buyer_context_version: null,
  fit_message: "Enter your criteria to assess fit",
  pending: [],
  financial_guidance: null,
  rejected_statements: 0,
  items: [],
  ...changes,
});

export const makeInputs = (changes: Partial<BuyerInputs> = {}): BuyerInputs => ({
  criteria: null,
  buyer_context: null,
  inputs: [],
  ...changes,
});

export const makeContext = (changes: Partial<BuyerContext> = {}): BuyerContext => ({
  relationship: "incumbent",
  current_share_pct: 12,
  contract_end_date: "2027-06-30",
  strategic_intent: ["dual_sourcing"],
  notes: "Qualification of a second source is under way.",
  version: 2,
  updated_by: "u1",
  updated_by_email: "claire@example.org",
  updated_at: "2026-10-28T09:00:00Z",
  ...changes,
});
