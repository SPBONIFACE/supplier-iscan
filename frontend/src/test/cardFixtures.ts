// Fixtures for the tests of the supplier card: a run, a profile definition, facts. Shared by the tests
// of the review (#36) and of the assessment section (#37).
import type { Fact, ProfileDefinition, Run } from "../lib/api";

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
