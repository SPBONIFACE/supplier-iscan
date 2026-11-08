import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import type { DemoProfile, DemoRun } from "../lib/api";
import {
  makeAssessment,
  makeDefinition,
  makeFact,
  makeNotFound,
  makeStatement,
} from "../test/cardFixtures";
import { expectNoCriticalIssues, fail, member, ok, renderApp } from "../test/utils";

const mocks = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  getDemoProfiles: vi.fn(),
  getDemoProfile: vi.fn(),
  getDemoComparison: vi.fn(),
  getDemoProfileDefinition: vi.fn(),
  downloadDemoProfilePdf: vi.fn(),
  // Every call that writes or asks a model: the demo must never reach one.
  startRun: vi.fn(),
  reviewFact: vi.fn(),
  reviewAssessmentStatement: vi.fn(),
  draftRunFit: vi.fn(),
  draftRunRecommendations: vi.fn(),
  putRunCriteria: vi.fn(),
  getOrganisation: vi.fn(),
  listRuns: vi.fn(),
}));

vi.mock("../lib/api", () => ({ api: mocks, setUnauthorizedHandler: vi.fn() }));

const DISCLAIMER = "Demo disclaimer: placeholder supplied by the owner.";
const ID = (n: number) => `00000000-0000-4000-8000-00000000000${n}`;

const demoRun = (n: number, changes: Partial<DemoRun> = {}): DemoRun => ({
  id: ID(n),
  supplier_name: `Forgeline ${n}`,
  supplier_website: "https://forgeline.example",
  supplier_country: "FR",
  supplier_sector: "Precision forging",
  natural_person: false,
  status: "completed",
  identity_to_verify: false,
  uncovered_sections: [],
  partial_explanation: null,
  excluded_sources: [],
  proposed_facts: 2,
  finished_at: "2026-10-14T10:00:00Z",
  profile_definition_hash: null,
  ...changes,
});

const profile = (n: number, changes: Partial<DemoRun> = {}): DemoProfile => ({
  run: demoRun(n, changes),
  facts: [
    makeFact("legal_form", "company_overview", { id: `f-${n}`, value: "SAS", quote: "Quote" }),
    makeNotFound("founding_year", "company_overview"),
  ],
  assessment: makeAssessment({
    items: [
      makeStatement(`s-${n}`, "strength", "A certified quality system.", {
        cited_fact_ids: [`f-${n}`],
      }),
    ],
  }),
  sources: [
    {
      url: "https://forgeline.example/about",
      fetched_at: "2026-10-12T10:00:00Z",
      content_type: "text/html",
    },
  ],
  disclaimer: DISCLAIMER,
});

beforeEach(async () => {
  vi.clearAllMocks();
  await i18n.changeLanguage("en");
  mocks.getCurrentUser.mockResolvedValue(fail("unauthorized", 401)); // a visitor
  mocks.getDemoProfiles.mockResolvedValue(
    ok({
      items: [demoRun(1), demoRun(2, { status: "partial", identity_to_verify: true })],
      disclaimer: DISCLAIMER,
    }),
  );
  mocks.getDemoProfile.mockImplementation((id: string) =>
    Promise.resolve(ok(profile(Number(id.slice(-1))))),
  );
  mocks.getDemoProfileDefinition.mockImplementation((language: "en" | "fr") =>
    Promise.resolve(ok(makeDefinition(language))),
  );
  mocks.getDemoComparison.mockImplementation((ids: string[]) =>
    Promise.resolve(
      ok({
        items: ids.map((id) => ({
          run: demoRun(Number(id.slice(-1))),
          facts: profile(Number(id.slice(-1))).facts,
        })),
        disclaimer: DISCLAIMER,
      }),
    ),
  );
});

const noWriteWasMade = () => {
  for (const name of [
    "startRun",
    "reviewFact",
    "reviewAssessmentStatement",
    "draftRunFit",
    "draftRunRecommendations",
    "putRunCriteria",
    "getOrganisation",
    "listRuns",
  ] as const) {
    expect(mocks[name]).not.toHaveBeenCalled();
  }
};

describe("the public demo", () => {
  it("offers Explore the demo on the landing page and on the login page, with no sign-in", async () => {
    const landing = renderApp("/demo");

    expect(
      (await screen.findByRole("link", { name: "Explore the demo" })).getAttribute("href"),
    ).toBe("/demo/profiles");
    expect(await screen.findByText(DISCLAIMER)).toBeTruthy();
    await expectNoCriticalIssues(landing.container);
    landing.unmount();

    renderApp("/login");
    expect(
      (await screen.findByRole("link", { name: "Explore the demo" })).getAttribute("href"),
    ).toBe("/demo");
    noWriteWasMade();
  });

  it("lists the demo profiles with the disclaimer, New profile disabled and its reason announced", async () => {
    const { container } = renderApp("/demo/profiles");

    expect(await screen.findByRole("link", { name: "Forgeline 1" })).toBeTruthy();
    expect(screen.getByText(DISCLAIMER)).toBeTruthy();
    const newProfile = screen.getByRole("button", { name: "New profile" });
    expect(newProfile.getAttribute("aria-disabled")).toBe("true");
    const why = document.getElementById(newProfile.getAttribute("aria-describedby") ?? "");
    expect(why?.textContent).toContain("Not available in the demo");
    expect(screen.getByText(/identity to verify/i)).toBeTruthy();
    await expectNoCriticalIssues(container);
    noWriteWasMade();
  });

  it("shows an empty state, not an error, when no demo profile is loaded", async () => {
    mocks.getDemoProfiles.mockResolvedValue(ok({ items: [], disclaimer: DISCLAIMER }));
    renderApp("/demo/profiles");

    expect(await screen.findByText("No demo profile loaded")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("opens a card read-only: review and re-run are disabled with the reason, the PDF is on", async () => {
    const { container } = renderApp(`/demo/profiles/${ID(1)}`);

    expect(await screen.findByRole("heading", { name: "Forgeline 1" })).toBeTruthy();
    expect(screen.getByText("A certified quality system.")).toBeTruthy();
    expect(screen.getAllByText("AI draft, pending your validation").length).toBeGreaterThan(0);
    expect((screen.getByRole("button", { name: "Re-run" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(screen.getAllByText(/Demo profiles are read-only/).length).toBeGreaterThan(0);
    expect(
      (screen.getByRole("button", { name: "Download PDF" }) as HTMLButtonElement).disabled,
    ).toBe(false);
    for (const button of screen.queryAllByRole("button", { name: /^(Approve|Correct|Delete)/ })) {
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
    await expectNoCriticalIssues(container);

    mocks.downloadDemoProfilePdf.mockResolvedValue(fail("unavailable", 503));
    await userEvent.click(screen.getByRole("button", { name: "Download PDF" }));
    expect(mocks.downloadDemoProfilePdf).toHaveBeenCalledWith(ID(1), "en");
    noWriteWasMade();
  });

  it("compares two demo profiles, facts only, with the disclaimer", async () => {
    const { container } = renderApp(`/demo/compare?profiles=${ID(1)},${ID(2)}`);

    expect(await screen.findByRole("heading", { name: /2 supplier profiles/i })).toBeTruthy();
    expect(screen.getByText(DISCLAIMER)).toBeTruthy();
    expect(mocks.getDemoComparison).toHaveBeenCalledWith([ID(1), ID(2)], "en");
    expect(screen.getAllByRole("link", { name: /Open card/ })[0].getAttribute("href")).toBe(
      `/demo/profiles/${ID(1)}`,
    );
    await expectNoCriticalIssues(container);
    noWriteWasMade();
  });

  it("answers an unknown profile with the not-found page and fewer than two with a note", async () => {
    mocks.getDemoProfile.mockResolvedValue(fail("not_found", 404));
    const first = renderApp(`/demo/profiles/${ID(9)}`);
    expect(await screen.findByRole("heading", { name: /not found/i })).toBeTruthy();
    first.unmount();

    renderApp(`/demo/compare?profiles=${ID(1)}`);
    expect(await screen.findByText(/2 or more|at least 2|two/i)).toBeTruthy();
    expect(mocks.getDemoComparison).not.toHaveBeenCalled();
  });

  it("works in French", async () => {
    await i18n.changeLanguage("fr");
    renderApp("/demo/profiles");

    expect(await screen.findByText("Profils de fournisseurs de la démo")).toBeTruthy();
    expect(mocks.getDemoProfiles).toHaveBeenCalledWith("fr");
  });

  it("lets a signed-in member open the demo without signing them out", async () => {
    mocks.getCurrentUser.mockResolvedValue(ok(member));
    renderApp("/demo/profiles");

    expect(await screen.findByRole("link", { name: "Forgeline 1" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
    await waitFor(() => expect(screen.getByText(member.email)).toBeTruthy());
  });

  it("does not send a visitor to the sign-in page", async () => {
    renderApp("/demo/profiles");

    expect(await screen.findByRole("link", { name: "Forgeline 1" })).toBeTruthy();
    expect(screen.getByTestId("where").textContent).toBe("/demo/profiles");
  });
});
