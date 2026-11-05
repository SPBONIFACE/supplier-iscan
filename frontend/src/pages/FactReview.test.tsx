// Review of facts on the supplier card (#36): approve, correct, conflicts, a run in progress, failures,
// the keyboard, EN and FR, and the accessibility check with the correction form open.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Fact } from "../lib/api";
import { CARD_PATH, makeDefinition, makeFact, makeNotFound, makeRun } from "../test/cardFixtures";
import { expectNoSeriousIssues, fail, member, ok, renderApp } from "../test/utils";

const mocks = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  getOrganisation: vi.fn(),
  listRuns: vi.fn(),
  getRun: vi.fn(),
  listRunFacts: vi.fn(),
  getProfileDefinition: vi.fn(),
  reviewFact: vi.fn(),
  listRunFailures: vi.fn(),
  listRunSources: vi.fn(),
  getDisclosure: vi.fn(),
}));

vi.mock("../lib/api", () => ({ api: mocks, setUnauthorizedHandler: vi.fn() }));

const facts = (): Fact[] => [
  makeFact("legal_form", "company_overview", {
    status: "approved",
    value: "SAS",
    reviewed_by: "u2",
    reviewed_by_email: "claire@example.org",
    reviewed_at: "2026-10-27T10:38:00Z",
    version: 2,
  }),
  makeFact("founding_year", "company_overview", { value: "1987" }),
  makeFact("employee_count", "company_overview", {
    value: "240 at the Vénissieux site",
    quote: "Le site compte 240 salariés.",
    source_type: "third_party",
  }),
  makeFact("quality_management", "certifications", { value: "EN 9100:2018" }),
  makeNotFound("environmental_management", "certifications"),
];

const row = (label: string) => {
  const item = screen.getAllByRole("listitem").find((li) => li.textContent?.startsWith(label));
  if (!item) throw new Error(`No row ${label}`);
  return item;
};

const reviewed = (fact: Fact, changes: Partial<Fact>): Fact => ({
  ...fact,
  reviewed_by: "u1",
  reviewed_by_email: member.email,
  reviewed_at: "2026-11-05T09:15:00Z",
  version: fact.version + 1,
  ...changes,
});

async function openCard() {
  renderApp(CARD_PATH);
  return screen.findByRole("dialog", { name: "Corvane Précision SAS" });
}

beforeEach(async () => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.getCurrentUser.mockResolvedValue(ok(member));
  mocks.getDisclosure.mockResolvedValue(ok({ language: "en", text: "disclosure" }));
  mocks.getOrganisation.mockResolvedValue(ok(null));
  mocks.listRunFailures.mockResolvedValue(fail("not_found", 404));
  mocks.listRunSources.mockResolvedValue(fail("not_found", 404));
  mocks.listRuns.mockResolvedValue(ok({ items: [makeRun()] }));
  mocks.getRun.mockResolvedValue(ok(makeRun()));
  mocks.listRunFacts.mockResolvedValue(ok({ items: facts() }));
  mocks.getProfileDefinition.mockImplementation(async (language: "en" | "fr") =>
    ok(makeDefinition(language)),
  );
  const { initI18n } = await import("../i18n");
  await initI18n("en");
});

describe("approve", () => {
  it("approves a fact, shows who and when, lowers the count and announces it", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    expect(within(panel).getByText("3 facts still proposed")).toBeTruthy();
    const year = row("Founding year");
    mocks.reviewFact.mockResolvedValue(ok(reviewed(facts()[1] as Fact, { status: "approved" })));
    mocks.getRun.mockResolvedValue(ok(makeRun({ proposed_facts: 2 })));

    await user.click(within(year).getByRole("button", { name: "Approve Founding year" }));

    expect(mocks.reviewFact).toHaveBeenCalledWith("fact-founding_year", {
      status: "approved",
      version: 1,
    });
    await waitFor(() => expect(within(year).getByText("Approved")).toBeTruthy());
    expect(
      within(year).getByText(/Approved by marie@example\.org on Nov 5, 2026, 09:15 UTC/),
    ).toBeTruthy();
    expect(within(year).queryByRole("button", { name: /Approve/ })).toBeNull();
    expect(within(panel).getByText("2 facts still proposed")).toBeTruthy();
    expect(
      within(panel).getByText("Founding year approved. 2 facts still proposed", {
        selector: "p[role=status]",
      }),
    ).toBeTruthy();
    expect(document.activeElement).toBe(year); // focus returns to the row
    expect(mocks.getRun).toHaveBeenCalledTimes(2); // the count is read again from the run
  });

  it("shows who approved a fact in the active locale (French)", async () => {
    const { initI18n } = await import("../i18n");
    await initI18n("fr");
    const panel = await openCard();
    const legal = row("Forme juridique");
    expect(
      within(legal).getByText(/Approuvé par claire@example\.org le 27\/10\/2026 10:38 UTC/),
    ).toBeTruthy();
    expect(within(panel).getByText("3 faits encore proposés")).toBeTruthy();
    expect(within(legal).getByRole("button", { name: "Corriger Forme juridique" })).toBeTruthy();
    expect(
      within(row("Année de création")).getByRole("button", { name: "Approuver Année de création" }),
    ).toBeTruthy();
  });

  it("has no review action on a field without evidence", async () => {
    await openCard();
    const env = row("Environmental management");
    expect(within(env).getByText("No public evidence found")).toBeTruthy();
    expect(within(env).queryByRole("button")).toBeNull();
  });
});

describe("correct", () => {
  it("flags an empty value inline and sends nothing", async () => {
    const user = userEvent.setup();
    await openCard();
    const year = row("Founding year");
    await user.click(within(year).getByRole("button", { name: "Correct Founding year" }));
    const field = within(year).getByLabelText("Corrected value") as HTMLInputElement;
    expect(field.value).toBe("1987");
    expect(document.activeElement).toBe(field);

    await user.clear(field);
    await user.type(field, "   {Enter}");

    expect(mocks.reviewFact).not.toHaveBeenCalled();
    expect(within(year).getByText("Error: enter the corrected value.")).toBeTruthy();
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(field.getAttribute("aria-describedby")).toContain(
      within(year).getByText("Error: enter the corrected value.").id,
    );
  });

  it("saves a correction with Enter, keeps the original AI value and its quote, and returns the focus", async () => {
    const user = userEvent.setup();
    await openCard();
    const employees = row("Number of employees");
    const base = facts()[2] as Fact;
    mocks.reviewFact.mockResolvedValue(
      ok(
        reviewed(base, {
          status: "corrected",
          value: "東京 · 245 à Vénissieux",
          original_value: base.value,
        }),
      ),
    );
    await user.click(
      within(employees).getByRole("button", { name: "Correct Number of employees" }),
    );
    const field = within(employees).getByLabelText("Corrected value");
    await user.clear(field);
    await user.type(field, "東京 · 245 à Vénissieux{Enter}");

    expect(mocks.reviewFact).toHaveBeenCalledWith("fact-employee_count", {
      status: "corrected",
      value: "東京 · 245 à Vénissieux",
      version: 1,
    });
    await waitFor(() => expect(within(employees).getByText("Corrected")).toBeTruthy());
    expect(within(employees).getByText("東京 · 245 à Vénissieux")).toBeTruthy();
    expect(
      within(employees).getByText(/Original AI value: 240 at the Vénissieux site/),
    ).toBeTruthy();
    expect(within(employees).getByText(/Corrected by marie@example\.org on/)).toBeTruthy();
    expect(within(employees).queryByLabelText("Corrected value")).toBeNull();
    expect(document.activeElement).toBe(employees);

    // The quote stays reachable and is said to support the original AI value.
    await user.click(within(employees).getByRole("button", { name: /Found in/ }));
    expect(
      within(employees).getByRole("heading", {
        name: "Quote for the original AI value · Number of employees",
      }),
    ).toBeTruthy();
    expect(within(employees).getByText("Le site compte 240 salariés.")).toBeTruthy();
  });

  it("a second correction replaces the value and the original stays", async () => {
    const user = userEvent.setup();
    const first = facts()[1] as Fact;
    const corrected = reviewed(first, {
      status: "corrected",
      value: "1988",
      original_value: "1987",
      version: 2,
    });
    mocks.listRunFacts.mockResolvedValue(ok({ items: [corrected] }));
    await openCard();
    const year = row("Founding year");
    mocks.reviewFact.mockResolvedValue(
      ok({ ...corrected, value: "1989", version: 3, original_value: "1987" }),
    );
    await user.click(within(year).getByRole("button", { name: "Correct Founding year" }));
    const field = within(year).getByLabelText("Corrected value");
    expect((field as HTMLInputElement).value).toBe("1988");
    await user.clear(field);
    await user.type(field, "1989{Enter}");

    expect(mocks.reviewFact).toHaveBeenCalledWith("fact-founding_year", {
      status: "corrected",
      value: "1989",
      version: 2,
    });
    await waitFor(() => expect(within(year).getByText("1989")).toBeTruthy());
    expect(within(year).getByText(/Original AI value: 1987/)).toBeTruthy();
    expect(within(year).queryByRole("button", { name: /Approve/ })).toBeNull(); // not approved over a correction
  });

  it("Escape cancels the form without closing the card, and focus returns to the row", async () => {
    const user = userEvent.setup();
    await openCard();
    const year = row("Founding year");
    await user.click(within(year).getByRole("button", { name: "Correct Founding year" }));
    await user.keyboard("{Escape}");

    expect(within(year).queryByLabelText("Corrected value")).toBeNull();
    expect(document.activeElement).toBe(year);
    expect(screen.getByRole("dialog", { name: "Corvane Précision SAS" })).toBeTruthy();
    expect(mocks.reviewFact).not.toHaveBeenCalled();
  });
});

describe("conflicts and failures", () => {
  it("on a concurrent change shows the current state, who changed it and keeps the typed text", async () => {
    const user = userEvent.setup();
    await openCard();
    const employees = row("Number of employees");
    const base = facts()[2] as Fact;
    const current = reviewed(base, {
      status: "corrected",
      value: "250 at the Vénissieux site",
      original_value: base.value,
      reviewed_by_email: "claire@example.org",
      reviewed_at: "2026-11-05T09:10:00Z",
    });
    mocks.reviewFact.mockResolvedValueOnce({
      ok: false,
      kind: "conflict",
      status: 409,
      errors: [],
      detail: "Someone reviewed this since you read it.",
      current,
    });
    await user.click(
      within(employees).getByRole("button", { name: "Correct Number of employees" }),
    );
    const field = within(employees).getByLabelText("Corrected value");
    await user.clear(field);
    await user.type(field, "245 at the site{Enter}");

    const alert = await within(employees).findByRole("alert");
    expect(alert.textContent).toMatch(
      /claire@example\.org changed this fact on Nov 5, 2026, 09:10 UTC, while you were editing\. Nothing was overwritten/,
    );
    expect(document.activeElement).toBe(alert);
    expect(within(employees).getByText("250 at the Vénissieux site")).toBeTruthy(); // the current state
    expect(within(employees).getByText(/Original AI value: 240/)).toBeTruthy();
    const kept = within(employees).getByLabelText(
      "Your corrected value (not saved)",
    ) as HTMLInputElement;
    expect(kept.value).toBe("245 at the site"); // the typed text is kept

    // Apply it over the current version.
    mocks.reviewFact.mockResolvedValueOnce(
      ok({ ...current, value: "245 at the site", version: current.version + 1 }),
    );
    await user.click(within(employees).getByRole("button", { name: "Apply my correction" }));
    expect(mocks.reviewFact).toHaveBeenLastCalledWith("fact-employee_count", {
      status: "corrected",
      value: "245 at the site",
      version: current.version,
    });
    await waitFor(() => expect(within(employees).queryByRole("alert")).toBeNull());
    expect(within(employees).getByText("245 at the site")).toBeTruthy();
  });

  it("lets the member discard the typed text after a conflict", async () => {
    const user = userEvent.setup();
    await openCard();
    const year = row("Founding year");
    const current = reviewed(facts()[1] as Fact, { status: "approved" });
    mocks.reviewFact.mockResolvedValue({
      ok: false,
      kind: "conflict",
      status: 409,
      errors: [],
      detail: "x",
      current,
    });
    await user.click(within(year).getByRole("button", { name: "Correct Founding year" }));
    await user.type(within(year).getByLabelText("Corrected value"), "0{Enter}");
    await within(year).findByRole("alert");
    await user.click(within(year).getByRole("button", { name: "Discard my text" }));

    expect(within(year).queryByLabelText(/corrected value/i)).toBeNull();
    expect(within(year).queryByRole("alert")).toBeNull();
    expect(within(year).getByText("Approved")).toBeTruthy();
    expect(document.activeElement).toBe(year);
  });

  it("disables the actions with the reason while the run is still in progress", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    const year = row("Founding year");
    mocks.reviewFact.mockResolvedValue({
      ok: false,
      kind: "conflict",
      status: 409,
      errors: [],
      detail: "The run is still in progress.",
    });
    await user.click(within(year).getByRole("button", { name: "Approve Founding year" }));

    const reason = await within(panel).findByText(/profile run is still in progress/);
    expect(reason).toBeTruthy();
    for (const button of within(panel).getAllByRole("button", { name: /^(Approve|Correct) / })) {
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
    expect(within(year).getByText("Proposed")).toBeTruthy();
  });

  it("shows an error and leaves the row unchanged on a 5xx or a network failure", async () => {
    const user = userEvent.setup();
    await openCard();
    const year = row("Founding year");
    mocks.reviewFact.mockResolvedValue(fail("unavailable", 0));
    await user.click(within(year).getByRole("button", { name: "Approve Founding year" }));

    const alert = await within(year).findByRole("alert");
    expect(alert.textContent).toMatch(
      /Error: the review could not be saved\. The row is unchanged/,
    );
    expect(within(year).getByText("Proposed")).toBeTruthy();
    expect(within(year).getByRole("button", { name: "Approve Founding year" })).toBeTruthy();
  });

  it("says plainly that a fact no longer exists (404) and offers to reload the card", async () => {
    const user = userEvent.setup();
    await openCard();
    const year = row("Founding year");
    mocks.reviewFact.mockResolvedValue(fail("not_found", 404));
    await user.click(within(year).getByRole("button", { name: "Approve Founding year" }));

    expect((await within(year).findByRole("alert")).textContent).toMatch(/no longer exists/);
    mocks.getRun.mockClear();
    await user.click(within(year).getByRole("button", { name: "Reload the card" }));
    await waitFor(() => expect(mocks.getRun).toHaveBeenCalled());
  });

  it("shows no message of its own on a 401: the app sends the member to sign in", async () => {
    const user = userEvent.setup();
    await openCard();
    const year = row("Founding year");
    mocks.reviewFact.mockResolvedValue(fail("unauthorized", 401));
    await user.click(within(year).getByRole("button", { name: "Approve Founding year" }));
    await waitFor(() => expect(mocks.reviewFact).toHaveBeenCalled());
    expect(within(year).queryByRole("alert")).toBeNull();
  });
});

describe("keyboard", () => {
  it("moves from fact to fact with the arrows, one tab stop per section", async () => {
    const user = userEvent.setup();
    await openCard();
    const legal = row("Legal form");
    const year = row("Founding year");
    expect(legal.getAttribute("tabindex")).toBe("0");
    expect(year.getAttribute("tabindex")).toBe("-1");
    legal.focus();
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(year);
    expect(year.getAttribute("tabindex")).toBe("0");
    expect(legal.getAttribute("tabindex")).toBe("-1");
    await user.keyboard("{End}");
    expect(document.activeElement).toBe(row("Number of employees"));
    await user.keyboard("{Home}");
    expect(document.activeElement).toBe(legal);
    await user.keyboard("{ArrowUp}");
    expect(document.activeElement).toBe(legal);
  });

  it("approves from the keyboard alone and goes to the next proposed fact", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await user.click(within(panel).getByRole("button", { name: "Go to the next proposed fact" }));
    const year = row("Founding year");
    expect(document.activeElement).toBe(year);
    mocks.reviewFact.mockResolvedValue(ok(reviewed(facts()[1] as Fact, { status: "approved" })));
    await user.tab(); // chip
    await user.tab(); // Approve
    expect(document.activeElement).toBe(
      within(year).getByRole("button", { name: "Approve Founding year" }),
    );
    await user.keyboard("{Enter}");
    await waitFor(() => expect(within(year).getByText("Approved")).toBeTruthy());
    expect(document.activeElement).toBe(year);
  });
});

describe("accessibility", () => {
  it("reports no serious issue with the correction form open", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    await user.click(within(panel).getByRole("button", { name: "Correct Founding year" }));
    await expectNoSeriousIssues(panel);
  });

  it("reports no serious issue with the conflict message and the kept text", async () => {
    const user = userEvent.setup();
    const panel = await openCard();
    const year = row("Founding year");
    mocks.reviewFact.mockResolvedValue({
      ok: false,
      kind: "conflict",
      status: 409,
      errors: [],
      detail: "x",
      current: reviewed(facts()[1] as Fact, { status: "approved" }),
    });
    await user.click(within(year).getByRole("button", { name: "Correct Founding year" }));
    await user.type(within(year).getByLabelText("Corrected value"), "0{Enter}");
    await within(year).findByRole("alert");
    await expectNoSeriousIssues(panel);
  });
});
