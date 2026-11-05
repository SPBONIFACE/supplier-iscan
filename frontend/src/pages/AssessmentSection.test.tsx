// The assessment section of the supplier card (#37): statements and recommendations, review, provenance,
// financial guidance, fit criteria, buyer context, buyer inputs, drafting, conflicts, natural-person
// identities, EN and FR, and the accessibility checks.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AssessmentStatement, Fact } from "../lib/api";
import {
  CARD_PATH,
  makeAssessment,
  makeContext,
  makeDefinition,
  makeFact,
  makeGuidance,
  makeInputs,
  makeNotFound,
  makeRun,
  makeStatement,
} from "../test/cardFixtures";
import { expectNoSeriousIssues, fail, member, ok, renderApp } from "../test/utils";

const mocks = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  getOrganisation: vi.fn(),
  listRuns: vi.fn(),
  getRun: vi.fn(),
  listRunFacts: vi.fn(),
  getProfileDefinition: vi.fn(),
  getRunAssessment: vi.fn(),
  getRunBuyerInputs: vi.fn(),
  reviewFact: vi.fn(),
  reviewAssessmentStatement: vi.fn(),
  putRunCriteria: vi.fn(),
  putRunBuyerContext: vi.fn(),
  putRunBuyerInput: vi.fn(),
  draftRunFit: vi.fn(),
  draftRunRecommendations: vi.fn(),
  listRunFailures: vi.fn(),
  listRunSources: vi.fn(),
  getDisclosure: vi.fn(),
}));

vi.mock("../lib/api", () => ({ api: mocks, setUnauthorizedHandler: vi.fn() }));

const FACTS: Fact[] = [
  makeFact("legal_form", "company_overview", { status: "approved", value: "SAS" }),
  makeFact("founding_year", "company_overview", { value: "1987" }),
  makeFact("employee_count", "company_overview", {
    status: "corrected",
    value: "250 at the site",
    original_value: "240 at the site",
    reviewed_by: "u1",
    reviewed_by_email: "claire@example.org",
    reviewed_at: "2026-10-30T10:00:00Z",
    version: 2,
  }),
  makeFact("quality_management", "certifications", { value: "EN 9100:2018" }),
  makeNotFound("environmental_management", "certifications"),
];

const ASSUMING = "Assuming a first evaluation of this supplier:";
const strength = makeStatement(
  "s1",
  "strength",
  "The supplier claims EN 9100:2018 certification.",
  {
    cited_fact_ids: ["fact-quality_management"],
  },
);
const weakness = makeStatement(
  "s2",
  "weakness",
  "Production depends on two sites.",
  { cited_fact_ids: ["fact-founding_year"] },
  {
    status: "approved",
    reviewed_by: "u2",
    reviewed_by_email: "claire@example.org",
    reviewed_at: "2026-10-27T10:38:00Z",
  },
);
const risk = makeStatement("s3", "risk_indicator", "Revenue concentration on aerospace.", {
  level: "medium",
  cited_fact_ids: ["fact-founding_year", "fact-employee_count"],
});
const gap = makeStatement(
  "s4",
  "evidence_gap",
  "No public evidence found of an ISO 14001 certificate.",
  {
    gap_evidence: "a current ISO 14001 certificate",
  },
);
const financial = makeStatement(
  "s5",
  "evidence_gap",
  "Financial statements for Corvane Précision SAS, financial year 2025: the income statement is not public.",
  {},
  { provider: "rules", model_id: "rules", model_version: "1" },
);
const reco = (
  id: string,
  kind: AssessmentStatement["kind"],
  text: string,
  changes: Partial<AssessmentStatement> = {},
  provenance: Partial<AssessmentStatement["provenance"]> = {},
) =>
  makeStatement(
    id,
    kind,
    text,
    { cited_fact_ids: ["fact-quality_management"], ...changes },
    { generated_at: "2026-10-26T16:06:00Z", ...provenance },
  );
const recoFirst = [
  reco("r1", "procurement_implication", `${ASSUMING} start with a qualification phase.`),
  reco("r2", "relationship_level", `${ASSUMING} a preferred relationship fits.`, {
    label: "preferred",
  }),
  reco("r3", "next_action", `${ASSUMING} ask for the certificate scope.`, {
    timing: "within 2 weeks",
  }),
  reco("r4", "procurement_priority", `${ASSUMING} medium.`, { level: "medium" }),
];

const statementEl = (id: string) => {
  const el = document.getElementById(`stmt-${id}`);
  if (!el) throw new Error(`No statement ${id}`);
  return el;
};

async function openCard() {
  renderApp(CARD_PATH);
  return screen.findByRole("dialog", { name: "Corvane Précision SAS" });
}

const withItems = (items: AssessmentStatement[], more: Parameters<typeof makeAssessment>[0] = {}) =>
  makeAssessment({ items, ...more });

beforeEach(async () => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.getCurrentUser.mockResolvedValue(ok(member));
  mocks.getDisclosure.mockResolvedValue(ok({ language: "en", text: "disclosure" }));
  mocks.getOrganisation.mockResolvedValue(ok(null));
  mocks.listRunFailures.mockResolvedValue(fail("not_found", 404));
  mocks.listRunSources.mockResolvedValue(fail("not_found", 404));
  mocks.listRuns.mockResolvedValue(ok({ items: [makeRun()] }));
  mocks.getRun.mockResolvedValue(ok(makeRun()));
  mocks.listRunFacts.mockResolvedValue(ok({ items: FACTS }));
  mocks.getProfileDefinition.mockImplementation(async (language: "en" | "fr") =>
    ok(makeDefinition(language)),
  );
  mocks.getRunAssessment.mockResolvedValue(
    ok(
      withItems([strength, weakness, risk, gap, financial, ...recoFirst], {
        financial_guidance: makeGuidance(),
      }),
    ),
  );
  mocks.getRunBuyerInputs.mockResolvedValue(ok(makeInputs()));
  const { initI18n } = await import("../i18n");
  await initI18n("en");
  vi.stubEnv("VITE_ASSESSMENT_POLL_INTERVAL_MS", "100");
});

describe("statements and recommendations", () => {
  it("groups statements, shows levels and citations, and no overall score", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Assessment/, level: 2 });
    for (const name of ["Strengths", "Weaknesses", "Risk indicators", "Evidence gaps"]) {
      expect(within(panel).getByRole("heading", { name, level: 3 })).toBeTruthy();
    }
    expect(within(panel).queryByRole("heading", { name: "Opportunities" })).toBeNull(); // none drafted
    expect(within(panel).getByText(/There is no overall score/)).toBeTruthy();

    const riskEl = statementEl("s3");
    expect(within(riskEl).getByText("medium")).toBeTruthy();
    expect(within(riskEl).getByText("Level:")).toBeTruthy();
    // Each cited fact links to its row on the card.
    const link = within(riskEl).getByRole("link", { name: "Founding year" });
    await user.click(link);
    expect(document.activeElement?.id).toBe("fact-fact-founding_year");

    const gapEl = statementEl("s4");
    expect(within(gapEl).getByText("Evidence gap", { selector: ".gap-label" })).toBeTruthy();
    expect(within(gapEl).getByText(/a current ISO 14001 certificate/)).toBeTruthy();
    expect(panel.textContent).not.toMatch(/\d\s*\/\s*(10|100)\b|score:\s*\d/i);
  });

  it("labels AI drafts until a member decides, and shows the review status after", async () => {
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Assessment/, level: 2 });
    expect(within(statementEl("s1")).getByText("AI draft, pending your validation")).toBeTruthy();
    const approved = statementEl("s2");
    expect(within(approved).queryByText("AI draft, pending your validation")).toBeNull();
    expect(within(approved).getByText("Approved")).toBeTruthy();
    expect(
      within(approved).getByText(/Reviewed by claire@example\.org on Oct 27, 2026, 10:38 UTC/),
    ).toBeTruthy();
  });

  it("shows the recommendations block with its labels, the first-evaluation assumption as drafted and the invitation to add the buyer context", async () => {
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Procurement recommendations/ });
    const invite = within(panel).getByText("No buyer context yet.").closest("div");
    expect(invite?.textContent).toMatch(/assume a first evaluation/);
    expect(within(panel).getByRole("button", { name: "Add buyer context" })).toBeTruthy();

    const implication = statementEl("r1");
    expect(
      within(implication).getByText("Overall procurement implication", { selector: ".reco-kind" }),
    ).toBeTruthy();
    expect(within(implication).getByText(ASSUMING).className).toBe("assume");
    expect(within(statementEl("r2")).getByText("preferred")).toBeTruthy();
    expect(within(statementEl("r2")).getByText("Relationship:")).toBeTruthy();
    expect(within(statementEl("r3")).getByText("within 2 weeks")).toBeTruthy();
    expect(within(statementEl("r4")).getByText("medium")).toBeTruthy();
    // Recommendations carry the AI-draft label and the review actions like any statement.
    expect(within(implication).getByText("AI draft, pending your validation")).toBeTruthy();
    expect(
      within(implication).getByRole("button", { name: "Approve Overall procurement implication" }),
    ).toBeTruthy();
  });

  it("marks recommendations drafted with an outdated buyer context and offers the redraft", async () => {
    const outdated = [
      reco("r1", "procurement_implication", "Corvane is a credible second source.", {
        buyer_context_version: 1,
        buyer_context_outdated: true,
        cites_buyer_context: true,
      }),
      reco(
        "r2",
        "relationship_level",
        "A preferred relationship fits.",
        {
          buyer_context_version: 1,
          buyer_context_outdated: true,
          label: "preferred",
        },
        {
          status: "approved",
          reviewed_by_email: "claire@example.org",
          reviewed_at: "2026-10-29T09:00:00Z",
        },
      ),
    ];
    mocks.getRunAssessment.mockResolvedValue(
      ok(
        withItems(outdated, {
          buyer_context_version: 1,
          current_buyer_context_version: 2,
        }),
      ),
    );
    mocks.getRunBuyerInputs.mockResolvedValue(ok(makeInputs({ buyer_context: makeContext() })));
    const panel = await openCard();

    expect(await within(panel).findByText("Buyer context changed since this draft")).toBeTruthy();
    expect(within(panel).getByText(/version 1\. Version 2 is stored now/i)).toBeTruthy();
    expect(
      within(statementEl("r1")).getByText("Not reviewed: the redraft will replace this draft."),
    ).toBeTruthy();
    expect(
      within(statementEl("r2")).getByText("Reviewed: the redraft leaves it unchanged."),
    ).toBeTruthy();
    // The recommendation names the buyer context it rests on.
    expect(
      within(statementEl("r1")).getByRole("link", { name: "Buyer context, version 1" }),
    ).toBeTruthy();
    // The stored context is shown apart, as entered by the member.
    expect(within(panel).getByText(/entered by you, not drafted by the AI/)).toBeTruthy();
    expect(within(panel).getByText(/Version 2 · saved by claire@example\.org/)).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "Redraft recommendations" })).toBeTruthy();
  });

  it("keeps the AI text of a statement citing a fact the buyer corrected since, says so and offers the redraft", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Assessment/, level: 2 });
    const citing = statementEl("s3"); // cites the employee count, corrected on Oct 30 after the Oct 26 draft
    expect(within(citing).getByText("Revenue concentration on aerospace.")).toBeTruthy();
    expect(citing.textContent).toMatch(
      /Cites a fact you corrected since this draft: Number of employees/,
    );
    expect(statementEl("s1").textContent).not.toMatch(/corrected since this draft/); // cites an untouched fact

    void user;
  });

  it("offers to redraft a recommendation that cites a fact the buyer corrected since the draft", async () => {
    const user = userEvent.setup();
    mocks.getRunAssessment.mockResolvedValue(
      ok(
        withItems([
          reco("r9", "contract_approach", "Renew for two years.", {
            cited_fact_ids: ["fact-employee_count"],
          }),
        ]),
      ),
    );
    mocks.draftRunRecommendations.mockResolvedValue(
      ok({ part: "recommendations", status: "queued" }),
    );
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Procurement recommendations/ });
    const el = statementEl("r9");
    expect(within(el).getByText("Renew for two years.")).toBeTruthy(); // the AI text is kept
    expect(el.textContent).toMatch(
      /Cites a fact you corrected since this draft: Number of employees/,
    );

    await user.click(within(el).getByRole("button", { name: "Redraft recommendations" }));

    expect(mocks.draftRunRecommendations).toHaveBeenCalledTimes(1);
  });

  it("replaces the whole section by neutral wording for a natural-person business", async () => {
    mocks.getRun.mockResolvedValue(ok(makeRun({ natural_person: true })));
    mocks.getRunAssessment.mockResolvedValue(
      ok(
        makeAssessment({
          status: "not_assessed",
          message: "Not assessed: natural-person business",
          fit_message: "Not assessed: natural-person business",
        }),
      ),
    );
    const panel = await openCard();

    expect(
      await within(panel).findByText(
        "The assessment is not prepared for this supplier because of its legal form. This says nothing about the supplier.",
      ),
    ).toBeTruthy();
    expect(within(panel).queryByText(/Procurement recommendations/)).toBeNull();
    expect(within(panel).queryByText(/Financial evidence/)).toBeNull();
    expect(within(panel).queryByText(/Fit against your criteria/)).toBeNull();
    expect(within(panel).queryByRole("button", { name: /Redraft|Draft fit/ })).toBeNull();
    expect(within(panel).queryByText(/credit|risk/i)).toBeNull();
  });

  it("does not let a partial run look complete", async () => {
    mocks.getRun.mockResolvedValue(
      ok(makeRun({ status: "partial", uncovered_sections: ["recommendations"] })),
    );
    mocks.getRunAssessment.mockResolvedValue(ok(withItems([strength], { status: "partial" })));
    const panel = await openCard();

    expect(await within(panel).findByText(/assessment is incomplete/)).toBeTruthy();
    const redraft = within(panel).getByRole("button", {
      name: "Redraft recommendations",
    }) as HTMLButtonElement;
    expect(redraft.disabled).toBe(true);
    expect(
      within(panel).getByText(
        "The run reached its cost budget; no further AI call is made for it.",
      ),
    ).toBeTruthy();
  });
});

describe("review", () => {
  it("approves a statement and shows the status, the reviewer and the time", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Assessment/, level: 2 });
    const el = statementEl("s1");
    mocks.reviewAssessmentStatement.mockResolvedValue(
      ok({
        ...strength,
        version: 2,
        provenance: {
          ...strength.provenance,
          status: "approved",
          reviewed_by_email: member.email,
          reviewed_at: "2026-11-05T09:15:00Z",
        },
      }),
    );

    await user.click(within(el).getByRole("button", { name: "Approve Strength" }));

    expect(mocks.reviewAssessmentStatement).toHaveBeenCalledWith("s1", {
      status: "approved",
      version: 1,
      text: undefined,
    });
    await waitFor(() => expect(within(el).getByText("Approved")).toBeTruthy());
    expect(
      within(el).getByText(/Reviewed by marie@example\.org on Nov 5, 2026, 09:15 UTC/),
    ).toBeTruthy();
    expect(within(el).queryByText("AI draft, pending your validation")).toBeNull();
    expect(within(el).queryByRole("button", { name: /Approve/ })).toBeNull();
  });

  it("flags an empty correction and sends nothing; a correction keeps the AI text in the provenance", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Assessment/, level: 2 });
    const el = statementEl("s1");
    await user.click(within(el).getByRole("button", { name: "Correct Strength" }));
    const field = within(el).getByLabelText("Corrected statement") as HTMLTextAreaElement;
    expect(field.value).toBe(strength.text);
    await user.clear(field);
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(mocks.reviewAssessmentStatement).not.toHaveBeenCalled();
    expect(within(el).getByText("Error: enter the statement text.")).toBeTruthy();
    expect(field.getAttribute("aria-invalid")).toBe("true");

    mocks.reviewAssessmentStatement.mockResolvedValue(
      ok({
        ...strength,
        version: 2,
        text: "東京 EN 9100 — à vérifier.",
        original_text: strength.text,
        provenance: {
          ...strength.provenance,
          status: "corrected",
          reviewed_by_email: member.email,
          reviewed_at: "2026-11-05T09:15:00Z",
        },
      }),
    );
    await user.type(field, "東京 EN 9100 — à vérifier.");
    await user.keyboard("{Control>}{Enter}{/Control}");

    expect(mocks.reviewAssessmentStatement).toHaveBeenCalledWith("s1", {
      status: "corrected",
      text: "東京 EN 9100 — à vérifier.",
      version: 1,
    });
    await waitFor(() => expect(within(el).getByText("Corrected")).toBeTruthy());
    expect(within(el).getByText("東京 EN 9100 — à vérifier.")).toBeTruthy();
    expect(document.activeElement).toBe(el);
    await user.click(within(el).getByRole("button", { name: /^Provenance/ }));
    expect(within(el).getByText("AI text")).toBeTruthy();
    expect(within(el).getByText(strength.text)).toBeTruthy();
  });

  it("asks before deleting; Escape keeps the statement; a deletion removes it and moves the focus", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Assessment/, level: 2 });
    const el = statementEl("s3");
    await user.click(within(el).getByRole("button", { name: "Delete Risk indicator" }));
    const dialog = within(el).getByRole("alertdialog");
    expect(dialog.textContent).toMatch(/Delete this statement\?/);
    expect(document.activeElement).toBe(
      within(el).getByRole("button", { name: "Delete statement" }),
    );
    await user.keyboard("{Escape}");
    expect(within(el).queryByRole("alertdialog")).toBeNull();
    expect(mocks.reviewAssessmentStatement).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(el);

    mocks.reviewAssessmentStatement.mockResolvedValue(
      ok({
        ...risk,
        version: 2,
        provenance: { ...risk.provenance, status: "deleted", reviewed_at: "2026-11-05T09:15:00Z" },
      }),
    );
    await user.click(within(el).getByRole("button", { name: "Delete Risk indicator" }));
    await user.click(within(el).getByRole("button", { name: "Delete statement" }));

    await waitFor(() => expect(document.getElementById("stmt-s3")).toBeNull());
    expect(mocks.reviewAssessmentStatement).toHaveBeenCalledWith("s3", {
      status: "deleted",
      version: 1,
      text: undefined,
    });
    // The group had only this statement: the focus goes to the heading of the section.
    await waitFor(() => expect(document.activeElement?.id).toBe("assessment-h"));
  });

  it("on a concurrent change shows the current statement and keeps the typed text", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Assessment/, level: 2 });
    const el = statementEl("s1");
    const current: AssessmentStatement = {
      ...strength,
      version: 2,
      text: "Colleague's wording.",
      original_text: strength.text,
      provenance: {
        ...strength.provenance,
        status: "corrected",
        reviewed_by_email: "claire@example.org",
        reviewed_at: "2026-11-05T09:10:00Z",
      },
    };
    mocks.reviewAssessmentStatement.mockResolvedValueOnce({
      ok: false,
      kind: "conflict",
      status: 409,
      errors: [],
      detail: "x",
      current,
    });
    await user.click(within(el).getByRole("button", { name: "Correct Strength" }));
    const field = within(el).getByLabelText("Corrected statement");
    await user.clear(field);
    await user.type(field, "My wording.");
    await user.keyboard("{Control>}{Enter}{/Control}");

    const alert = await within(el).findByRole("alert");
    expect(alert.textContent).toMatch(
      /claire@example\.org changed this statement on Nov 5, 2026, 09:10 UTC, while you were editing\. Nothing was overwritten/,
    );
    expect(
      (within(el).getByLabelText("Your corrected statement (not saved)") as HTMLTextAreaElement)
        .value,
    ).toBe("My wording.");
    // The current statement is the one now held (its version is used for the next save).
    mocks.reviewAssessmentStatement.mockResolvedValueOnce(
      ok({ ...current, version: 3, text: "My wording." }),
    );
    await user.click(within(el).getByRole("button", { name: "Apply my correction" }));
    expect(mocks.reviewAssessmentStatement).toHaveBeenLastCalledWith("s1", {
      status: "corrected",
      text: "My wording.",
      version: 2,
    });
  });

  it("disables the review actions with the reason when the run is still in progress", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Assessment/, level: 2 });
    mocks.reviewAssessmentStatement.mockResolvedValue({
      ok: false,
      kind: "conflict",
      status: 409,
      errors: [],
      detail: "The run is still in progress.",
    });
    await user.click(within(statementEl("s1")).getByRole("button", { name: "Approve Strength" }));

    expect(await within(panel).findByText(/statements cannot be reviewed yet/)).toBeTruthy();
    for (const button of within(statementEl("s3")).getAllByRole("button", {
      name: /^(Approve|Correct|Delete) /,
    })) {
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
  });

  it("shows an error and leaves the statement unchanged on a failure", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Assessment/, level: 2 });
    mocks.reviewAssessmentStatement.mockResolvedValue(fail("unavailable", 503));
    const el = statementEl("s1");
    await user.click(within(el).getByRole("button", { name: "Approve Strength" }));
    expect((await within(el).findByRole("alert")).textContent).toMatch(
      /Error: the review could not be saved/,
    );
    expect(within(el).getByText("AI draft, pending your validation")).toBeTruthy();
  });
});

describe("provenance and financial guidance", () => {
  it("opens the provenance with the keyboard: provider, model, time and review status", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Assessment/, level: 2 });
    const el = statementEl("s1");
    const button = within(el).getByRole("button", { name: /^Provenance/ });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    button.focus();
    await user.keyboard("{Enter}");
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(within(el).getByText("google")).toBeTruthy();
    expect(within(el).getByText("gemini-flash-sample · 2026-09")).toBeTruthy();
    expect(within(el).getByText("Oct 26, 2026, 16:04 UTC")).toBeTruthy();
    expect(within(el).getByText("AI draft (not reviewed yet)")).toBeTruthy();
    await user.keyboard("{Enter}");
    expect(button.getAttribute("aria-expanded")).toBe("false");
  });

  it("shows the financial guidance: documents, access status, missing evidence, registry and date; provenance reads rules", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    const heading = await within(panel).findByRole("heading", { name: /Financial evidence/ });
    expect(heading.textContent).toMatch(/from rules, not AI/);
    const el = statementEl("s5");
    expect(within(el).getByText("Pending your validation")).toBeTruthy(); // not an AI draft
    expect(within(el).queryByText("AI draft, pending your validation")).toBeNull();
    const table = within(el).getByRole("table", { name: "Documents for financial year 2025" });
    expect(within(table).getByText("Free with registration")).toBeTruthy();
    expect(within(table).getByText("Confidentiality declared")).toBeTruthy();
    expect(within(table).getByText("No filing identified")).toBeTruthy();
    expect(within(table).getByText("Paid access")).toBeTruthy();
    expect(within(el).getByText("Group (parent or consolidated accounts)")).toBeTruthy();
    expect(
      within(el).getByText(/Income statement; Audit report; Supplier-entity accounts/),
    ).toBeTruthy();
    expect(within(el).getByText(/Statutory accounts; Audited statements/)).toBeTruthy();
    const registry = within(el).getByRole("link", { name: /National companies registry/ });
    expect(registry.getAttribute("href")).toBe("https://registry.example/fr");
    expect(registry.getAttribute("target")).toBe("_blank");
    expect(within(el).getByText("Oct 1, 2026")).toBeTruthy();
    expect(within(el).queryByText(/example table, not verified/)).toBeNull();

    await user.click(within(el).getByRole("button", { name: /^Provenance/ }));
    expect(within(el).getByText("Rules in code (no AI model)")).toBeTruthy();
    expect(within(el).queryByText(/gemini/)).toBeNull();
  });

  it("always shows that an example table is not verified", async () => {
    mocks.getRunAssessment.mockResolvedValue(
      ok(withItems([financial], { financial_guidance: makeGuidance({ example_table: true }) })),
    );
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Financial evidence/ });
    expect(within(panel).getByText("example table, not verified")).toBeTruthy();
    expect(within(panel).getByText(/placeholders and have not been verified/)).toBeTruthy();
  });

  it("never labels a paid, reduced or unreachable-registry document as unavailable", async () => {
    mocks.getRunAssessment.mockResolvedValue(
      ok(
        withItems([financial], {
          financial_guidance: makeGuidance({
            documents: [
              {
                type: "balance_sheet",
                scope: "supplier_entity",
                access: "paid",
                registry_link: null,
              },
              {
                type: "income_statement",
                scope: "supplier_entity",
                access: "reduced_disclosure",
                registry_link: null,
              },
              {
                type: "audit_report",
                scope: "supplier_entity",
                access: "registry_unavailable",
                registry_link: null,
              },
              {
                type: "notes",
                scope: "supplier_entity",
                access: "public_download",
                registry_link: null,
              },
            ],
          }),
        }),
      ),
    );
    const panel = await openCard();
    const table = await within(panel).findByRole("table");
    expect(table.textContent).toMatch(/Paid access/);
    expect(table.textContent).toMatch(/Reduced disclosure/);
    expect(table.textContent).toMatch(
      /Registry not reachable \(this does not show that no filing exists\)/,
    );
    expect(table.textContent).toMatch(/Public download/);
    expect(table.textContent).not.toMatch(/unavailable/i);
  });
});

describe("fit criteria and drafting", () => {
  it("invites the member to enter criteria and keeps the draft action disabled with its reason", async () => {
    const panel = await openCard();
    expect(await within(panel).findByText(/Enter your criteria to assess fit/)).toBeTruthy();
    const draft = within(panel).getByRole("button", {
      name: "Draft fit statements",
    }) as HTMLButtonElement;
    expect(draft.disabled).toBe(true);
    expect(within(panel).getByText("Save your criteria first.")).toBeTruthy();
  });

  it("saves the criteria with the version, then drafts fit statements and follows the drafting until they appear", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await within(panel).findByText(/Enter your criteria to assess fit/);
    await user.click(within(panel).getByRole("button", { name: "Go to the criteria field" }));
    const field = within(panel).getByLabelText("Your fit criteria for this supplier");
    expect(document.activeElement).toBe(field);
    const saved = {
      criteria: ["EN 9100 certified", "Five-axis titanium machining"],
      version: 1,
      updated_by: "u1",
      updated_by_email: member.email,
      updated_at: "2026-11-05T09:00:00Z",
    };
    mocks.putRunCriteria.mockResolvedValue(ok(saved));
    mocks.getRunBuyerInputs.mockResolvedValue(ok(makeInputs({ criteria: saved })));
    await user.type(field, "EN 9100 certified{Enter}Five-axis titanium machining");
    await user.click(within(panel).getByRole("button", { name: "Save criteria" }));

    expect(mocks.putRunCriteria).toHaveBeenCalledWith(expect.any(String), {
      criteria: ["EN 9100 certified", "Five-axis titanium machining"],
      version: 0,
    });
    expect(await within(panel).findByText("EN 9100 certified")).toBeTruthy();
    expect(within(panel).getByText(/Saved by marie@example\.org on Nov 5, 2026/)).toBeTruthy();
    expect(within(panel).getByText("Criteria saved.", { selector: "p[role=status]" })).toBeTruthy();

    // Drafting: 202, then a drafting indicator while the endpoint lists the part as pending.
    const draftButton = within(panel).getByRole("button", {
      name: "Draft fit statements",
    }) as HTMLButtonElement;
    expect(draftButton.disabled).toBe(false);
    mocks.draftRunFit.mockResolvedValue(ok({ part: "fit", status: "queued" }));
    const fit = makeStatement(
      "f1",
      "fit",
      "EN 9100 certified: claimed for the site.",
      { cited_fact_ids: ["fact-quality_management"] },
      { generated_at: "2026-11-05T09:05:00Z" },
    );
    mocks.getRunAssessment
      .mockResolvedValueOnce(ok(withItems([strength], { pending: ["fit"] })))
      .mockResolvedValue(ok(withItems([strength, fit])));
    await user.click(draftButton);

    expect(await within(panel).findByText("Drafting fit statements…")).toBeTruthy();
    expect(
      await within(panel).findByText(
        "EN 9100 certified: claimed for the site.",
        {},
        { timeout: 3000 },
      ),
    ).toBeTruthy();
    expect(within(panel).queryByText("Drafting fit statements…")).toBeNull();
    // The new statement has the same label and review actions as the others.
    expect(within(statementEl("f1")).getByText("AI draft, pending your validation")).toBeTruthy();
    expect(
      within(statementEl("f1")).getByRole("button", { name: "Approve Fit statement" }),
    ).toBeTruthy();
  });

  it("says plainly when the criteria were saved by someone else meanwhile and keeps the text", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await within(panel).findByText(/Enter your criteria to assess fit/);
    const other = {
      criteria: ["Delivery within 6 weeks"],
      version: 3,
      updated_by: "u2",
      updated_by_email: "claire@example.org",
      updated_at: "2026-11-05T08:00:00Z",
    };
    mocks.putRunCriteria.mockResolvedValue({
      ok: false,
      kind: "conflict",
      status: 409,
      errors: [],
      detail: "x",
      current: other,
    });
    await user.type(
      within(panel).getByLabelText("Your fit criteria for this supplier"),
      "My criterion",
    );
    await user.click(within(panel).getByRole("button", { name: "Save criteria" }));

    const alert = await within(panel).findByText(
      /claire@example\.org saved other criteria on Nov 5, 2026/,
    );
    expect(alert).toBeTruthy();
    expect(within(panel).getByText("Delivery within 6 weeks")).toBeTruthy();
    expect(
      (within(panel).getByLabelText("Your fit criteria for this supplier") as HTMLTextAreaElement)
        .value,
    ).toBe("My criterion");
  });

  it("gives a clear message for a refusal on the monthly spend cap, a conflict and a failure", async () => {
    const user = userEvent.setup();
    const saved = {
      criteria: ["EN 9100"],
      version: 1,
      updated_by: "u1",
      updated_by_email: member.email,
      updated_at: "2026-11-05T09:00:00Z",
    };
    mocks.getRunBuyerInputs.mockResolvedValue(ok(makeInputs({ criteria: saved })));
    const panel = await openCard();
    const draft = await within(panel).findByRole("button", { name: "Draft fit statements" });

    mocks.draftRunFit.mockResolvedValueOnce({
      ok: false,
      kind: "refused",
      status: 403,
      errors: [],
      reason: "spend_cap_reached",
    });
    await user.click(draft);
    expect(
      await within(panel).findByText(/monthly limit on AI spend of this service is reached/),
    ).toBeTruthy();

    mocks.draftRunFit.mockResolvedValueOnce({
      ok: false,
      kind: "conflict",
      status: 409,
      errors: [],
      detail: "The run reached its cost budget; no further AI call is made for it.",
    });
    await user.click(within(panel).getByRole("button", { name: "Draft fit statements" }));
    await waitFor(() =>
      expect(
        within(panel).getAllByText(
          "The run reached its cost budget; no further AI call is made for it.",
        ).length,
      ).toBeGreaterThan(0),
    );

    mocks.draftRunFit.mockResolvedValueOnce(fail("unavailable", 503));
    await user.click(within(panel).getByRole("button", { name: "Draft fit statements" }));
    expect(await within(panel).findByText(/the drafting could not be requested/)).toBeTruthy();
  });

  it("redrafts recommendations, shows the drafting indicator and says when nothing new was added", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    mocks.draftRunRecommendations.mockResolvedValue(
      ok({ part: "recommendations", status: "queued" }),
    );
    mocks.getRunAssessment
      .mockResolvedValueOnce(ok(withItems(recoFirst, { pending: ["recommendations"] })))
      .mockResolvedValue(ok(withItems(recoFirst)));
    await user.click(await within(panel).findByRole("button", { name: "Redraft recommendations" }));

    expect(await within(panel).findByText("Drafting recommendations…")).toBeTruthy();
    expect(
      await within(panel).findByText(/No new draft was added/, {}, { timeout: 3000 }),
    ).toBeTruthy();
    expect(within(panel).queryByText("Drafting recommendations…")).toBeNull();
  });
});

describe("buyer context", () => {
  it("opens the form in place of the card body, shows the field errors, saves with the version and returns", async () => {
    const user = userEvent.setup();
    mocks.getRunBuyerInputs.mockResolvedValue(ok(makeInputs({ buyer_context: makeContext() })));
    const panel = await openCard();
    await user.click(await within(panel).findByRole("button", { name: "Edit buyer context" }));

    expect(within(panel).getByRole("heading", { name: /Buyer context/, level: 2 })).toBeTruthy();
    expect(within(panel).queryByRole("heading", { name: /Assessment/ })).toBeNull();
    expect(
      within(panel).getByText(
        /Last saved by claire@example\.org on Oct 28, 2026.*version 2.*version 3/,
      ),
    ).toBeTruthy();
    expect((within(panel).getByLabelText("Incumbent supplier") as HTMLInputElement).checked).toBe(
      true,
    );
    expect((within(panel).getByLabelText("Dual sourcing") as HTMLInputElement).checked).toBe(true);

    // A value out of range is flagged on its field and sent nowhere.
    const share = within(panel).getByLabelText("Current share of your category spend (%)");
    await user.clear(share);
    await user.type(share, "140");
    const end = within(panel).getByLabelText("Contract end date");
    await user.clear(end);
    await user.type(end, "2027-13-31");
    await user.click(within(panel).getByRole("button", { name: "Save buyer context" }));
    expect(mocks.putRunBuyerContext).not.toHaveBeenCalled();
    const summary = await within(panel).findByRole("alert");
    expect(summary.textContent).toMatch(/2 fields need a correction/);
    expect(share.getAttribute("aria-invalid")).toBe("true");
    expect(within(panel).getByText("Enter a number from 0 to 100, for example 12.")).toBeTruthy();

    await user.clear(share);
    await user.type(share, "15");
    await user.clear(end);
    await user.type(end, "2027-09-30");
    await user.click(within(panel).getByLabelText("Cost reduction"));
    const saved = makeContext({
      version: 3,
      current_share_pct: 15,
      contract_end_date: "2027-09-30",
      strategic_intent: ["dual_sourcing", "cost_reduction"],
    });
    mocks.putRunBuyerContext.mockResolvedValue(ok(saved));
    mocks.getRunBuyerInputs.mockResolvedValue(ok(makeInputs({ buyer_context: saved })));
    await user.click(within(panel).getByRole("button", { name: "Save buyer context" }));

    expect(mocks.putRunBuyerContext).toHaveBeenCalledWith(expect.any(String), {
      relationship: "incumbent",
      current_share_pct: 15,
      contract_end_date: "2027-09-30",
      strategic_intent: ["dual_sourcing", "cost_reduction"],
      notes: "Qualification of a second source is under way.",
      version: 2,
    });
    expect(
      await within(panel).findByRole("heading", { name: /Assessment/, level: 2 }),
    ).toBeTruthy();
    expect(within(panel).getByText(/Version 3 · saved by claire@example\.org/)).toBeTruthy();
  });

  it("shows a server validation error on the field", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await user.click(await within(panel).findByRole("button", { name: "Add buyer context" }));
    mocks.putRunBuyerContext.mockResolvedValue({
      ok: false,
      kind: "validation",
      status: 422,
      errors: [{ field: "notes", message: "Notes are too long." }],
    });
    await user.type(within(panel).getByLabelText("Notes"), "x");
    await user.click(within(panel).getByRole("button", { name: "Save buyer context" }));

    expect(mocks.putRunBuyerContext).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ relationship: "new", version: 0 }),
    );
    expect(
      await within(panel).findByText(
        "These notes cannot be saved. Check that they are not too long.",
      ),
    ).toBeTruthy();
    expect(within(panel).getByLabelText("Notes").getAttribute("aria-invalid")).toBe("true");
  });

  it("on a conflict shows the stored context and keeps the member's entries", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await user.click(await within(panel).findByRole("button", { name: "Add buyer context" }));
    const theirs = makeContext({ version: 1, notes: "Their notes." });
    mocks.putRunBuyerContext.mockResolvedValue({
      ok: false,
      kind: "conflict",
      status: 409,
      errors: [],
      detail: "x",
      current: theirs,
    });
    await user.type(within(panel).getByLabelText("Notes"), "My notes");
    await user.click(within(panel).getByRole("button", { name: "Save buyer context" }));

    expect((await within(panel).findByRole("alert")).textContent).toMatch(
      /claire@example\.org saved a newer buyer context on Oct 28, 2026/,
    );
    expect(within(panel).getByText("Their notes.")).toBeTruthy();
    expect((within(panel).getByLabelText("Notes") as HTMLTextAreaElement).value).toBe("My notes");
    mocks.putRunBuyerContext.mockResolvedValue(ok(makeContext({ version: 2, notes: "My notes" })));
    await user.click(within(panel).getByRole("button", { name: "Save again and replace" }));
    expect(mocks.putRunBuyerContext).toHaveBeenLastCalledWith(
      expect.any(String),
      expect.objectContaining({ notes: "My notes", version: 1 }),
    );
  });
});

describe("buyer inputs", () => {
  it("shows a free-text field per buyer field, with who saved it, apart from AI content", async () => {
    mocks.getRunBuyerInputs.mockResolvedValue(
      ok(
        makeInputs({
          inputs: [
            {
              field: "buyer_notes",
              text: "Visited in September.",
              version: 2,
              updated_by: "u2",
              updated_by_email: "claire@example.org",
              updated_at: "2026-10-20T17:31:00Z",
            },
          ],
        }),
      ),
    );
    const panel = await openCard();
    const section = (
      await within(panel).findByRole("heading", { name: "Buyer input", level: 2 })
    ).closest("section") as HTMLElement;
    expect((within(section).getByLabelText("Buyer notes") as HTMLTextAreaElement).value).toBe(
      "Visited in September.",
    );
    expect(
      within(section).getByText(/Last saved by claire@example\.org on Oct 20, 2026, 17:31 UTC/),
    ).toBeTruthy();
    expect(within(section).getByText("Not saved yet")).toBeTruthy(); // Commercial history
    expect(within(section).queryByText(/AI draft/)).toBeNull();
    expect(within(section).queryByRole("button", { name: /Provenance/ })).toBeNull();
  });

  it("saves a changed field with its version; a conflict shows the stored text and keeps the member's", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    const section = (
      await within(panel).findByRole("heading", { name: "Buyer input", level: 2 })
    ).closest("section") as HTMLElement;
    mocks.putRunBuyerInput.mockResolvedValue(
      ok({
        field: "buyer_notes",
        text: "Good tooling.",
        version: 1,
        updated_by: "u1",
        updated_by_email: member.email,
        updated_at: "2026-11-05T09:00:00Z",
      }),
    );
    await user.type(within(section).getByLabelText("Buyer notes"), "Good tooling.");
    await user.click(within(section).getByRole("button", { name: "Save buyer input" }));
    expect(mocks.putRunBuyerInput).toHaveBeenCalledWith(expect.any(String), "buyer_notes", {
      text: "Good tooling.",
      version: 0,
    });
    expect(mocks.putRunBuyerInput).toHaveBeenCalledTimes(1); // only the changed field

    const theirs = {
      field: "buyer_history",
      text: "Two orders in 2025.",
      version: 4,
      updated_by: "u2",
      updated_by_email: "claire@example.org",
      updated_at: "2026-11-05T08:30:00Z",
    };
    mocks.putRunBuyerInput.mockResolvedValue({
      ok: false,
      kind: "conflict",
      status: 409,
      errors: [],
      detail: "x",
      current: theirs,
    });
    await user.type(within(section).getByLabelText("Commercial history"), "One late delivery.");
    await user.click(within(section).getByRole("button", { name: "Save buyer input" }));

    expect(
      await within(section).findByText(/claire@example\.org saved this field on Nov 5, 2026/),
    ).toBeTruthy();
    expect(within(section).getByText("Two orders in 2025.")).toBeTruthy();
    expect(
      (within(section).getByLabelText("Commercial history") as HTMLTextAreaElement).value,
    ).toBe("One late delivery.");
  });
});

describe("states and access", () => {
  it("shows a loading state, then an error with a retry action", async () => {
    const user = userEvent.setup();
    mocks.getRunAssessment.mockResolvedValueOnce(fail("unavailable", 503));
    const panel = await openCard();
    const alert = await within(panel).findByText(/the assessment could not be loaded/);
    expect(alert).toBeTruthy();
    mocks.getRunAssessment.mockResolvedValue(ok(withItems([strength])));
    await user.click(within(panel).getByRole("button", { name: "Try again" }));
    expect(await within(panel).findByRole("heading", { name: "Strengths" })).toBeTruthy();
  });

  it("shows the not-found page when the assessment's run is not found (another organisation's run)", async () => {
    mocks.getRunAssessment.mockResolvedValue(fail("not_found", 404));
    const panel = await openCard();
    expect(await within(panel).findByText("Page not found")).toBeTruthy();
  });

  it("shows that the assessment is still being prepared", async () => {
    mocks.getRunAssessment.mockResolvedValue(ok(makeAssessment({ status: "pending" })));
    const panel = await openCard();
    expect(await within(panel).findByText(/assessment is still being prepared/)).toBeTruthy();
    expect(within(panel).queryByRole("button", { name: /Redraft/ })).toBeNull();
  });

  it("renders the section in French with French dates and typography", async () => {
    const { initI18n } = await import("../i18n");
    await initI18n("fr");
    mocks.getRunBuyerInputs.mockResolvedValue(ok(makeInputs({ buyer_context: makeContext() })));
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Évaluation/, level: 2 });
    expect(
      within(statementEl("s1")).getByText("Brouillon IA, en attente de votre validation"),
    ).toBeTruthy();
    expect(
      within(statementEl("s2")).getByText(/Revu par claire@example\.org le 27\/10\/2026 10:38 UTC/),
    ).toBeTruthy();
    expect(within(statementEl("s3")).getByText("Niveau :")).toBeTruthy(); // a no-break space before the colon
    expect(within(statementEl("s3")).getByText("moyen")).toBeTruthy();
    expect(within(panel).getByRole("heading", { name: /Éléments financiers/ })).toBeTruthy();
    expect(within(panel).getByText("Gratuit avec inscription")).toBeTruthy();
    expect(
      within(panel).getAllByText("Information manquante", { selector: ".gap-label" }).length,
    ).toBeTruthy();
    expect(within(panel).getByText(/12\s?%/)).toBeTruthy();
    expect(
      within(panel).getByRole("button", { name: "Modifier le contexte acheteur" }),
    ).toBeTruthy();
  });
});

describe("accessibility", () => {
  it("reports no serious issue with a statement under review", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Assessment/, level: 2 });
    await user.click(within(statementEl("s1")).getByRole("button", { name: "Correct Strength" }));
    await expectNoSeriousIssues(panel);
  });

  it("reports no serious issue with the delete confirmation and the provenance open", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Assessment/, level: 2 });
    await user.click(within(statementEl("s1")).getByRole("button", { name: /^Provenance/ }));
    await user.click(
      within(statementEl("s3")).getByRole("button", { name: "Delete Risk indicator" }),
    );
    await expectNoSeriousIssues(panel);
  });

  it("reports no serious issue with the whole section, the financial guidance and the buyer inputs", async () => {
    const panel = await openCard();
    await within(panel).findByRole("heading", { name: /Assessment/, level: 2 });
    await expectNoSeriousIssues(panel);
  });

  it("reports no serious issue with the buyer context form open, with errors", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await user.click(await within(panel).findByRole("button", { name: "Add buyer context" }));
    await user.type(
      within(panel).getByLabelText("Current share of your category spend (%)"),
      "200",
    );
    await user.click(within(panel).getByRole("button", { name: "Save buyer context" }));
    await within(panel).findByRole("alert");
    await expectNoSeriousIssues(panel);
  });
});
