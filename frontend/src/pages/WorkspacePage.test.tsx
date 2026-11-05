import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { safeNext } from "../auth/paths";
import type { MemberOrganisation, Run } from "../lib/api";
import { expectNoCriticalIssues, fail, member, ok, renderApp } from "../test/utils";

const mocks = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  listRuns: vi.fn(),
  getOrganisation: vi.fn(),
  getDisclosure: vi.fn(),
  getRun: vi.fn(),
  listRunFailures: vi.fn(),
  listRunSources: vi.fn(),
  listRunFacts: vi.fn(),
  getProfileDefinition: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  api: {
    getCurrentUser: mocks.getCurrentUser,
    listRuns: mocks.listRuns,
    getOrganisation: mocks.getOrganisation,
    getDisclosure: mocks.getDisclosure,
    getRun: mocks.getRun,
    listRunFailures: mocks.listRunFailures,
    listRunSources: mocks.listRunSources,
    listRunFacts: mocks.listRunFacts,
    getProfileDefinition: mocks.getProfileDefinition,
  },
  setUnauthorizedHandler: vi.fn(),
}));

const where = () => screen.getByTestId("where").textContent;

const organisation = (changes: Partial<MemberOrganisation> = {}): MemberOrganisation => ({
  name: "Corvane Group",
  status: "active",
  seat_limit: null,
  profile_quota: 9,
  profiles_remaining: 4,
  run_refusal_reason: null,
  access_ends_at: "2026-12-31T00:00:00Z",
  ...changes,
});

const run = (id: string, name: string | null, status: Run["status"], at: string): Run =>
  ({
    id,
    supplier_name: name,
    status,
    created_at: at,
    started_at: null,
    finished_at: null,
  }) as Run;

const ALL: Run["status"][] = [
  "queued",
  "running",
  "paused",
  "stopped",
  "failed",
  "insufficient_sources",
  "partial",
  "completed",
];
const LABELS_EN = [
  "Queued",
  "Running",
  "Paused",
  "Stopped",
  "Failed",
  "Insufficient sources",
  "Partial",
  "Complete",
];
const rows = ALL.map((status, index) =>
  run(`run-${status}`, `Supplier ${index}`, status, "2026-10-27T10:00:00Z"),
);

beforeEach(async () => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.getCurrentUser.mockResolvedValue(ok(member));
  mocks.getDisclosure.mockResolvedValue(ok({ language: "en", text: "disclosure" }));
  // The run screen is opened by some tests; it only has to find nothing.
  mocks.getRun.mockResolvedValue(fail("not_found", 404));
  mocks.listRunFailures.mockResolvedValue(fail("not_found", 404));
  mocks.listRunSources.mockResolvedValue(fail("not_found", 404));
  const { initI18n } = await import("../i18n");
  await initI18n("en");
});

describe("workspace list", () => {
  it("shows a loading indicator, then every run with its status and date", async () => {
    mocks.listRuns.mockResolvedValue(ok({ items: rows }));
    mocks.getOrganisation.mockResolvedValue(ok(organisation()));
    renderApp("/workspace");
    expect(await screen.findByText("Loading…")).toBeTruthy();
    const table = await screen.findByRole("table");
    const bodyRows = within(table).getAllByRole("row").slice(1);
    expect(bodyRows).toHaveLength(8);
    LABELS_EN.forEach((label, index) => {
      expect(within(bodyRows[index] as HTMLElement).getByText(label)).toBeTruthy();
      expect(within(bodyRows[index] as HTMLElement).getByText("Oct 27, 2026")).toBeTruthy();
    });
    expect(screen.getByText(/Profiles remaining: 4 of 9/)).toBeTruthy();
    expect(screen.getByText(/Access until Dec 31, 2026/)).toBeTruthy();
  });

  it("says unlimited when no quota is set", async () => {
    mocks.listRuns.mockResolvedValue(ok({ items: rows }));
    mocks.getOrganisation.mockResolvedValue(
      ok(organisation({ profile_quota: null, profiles_remaining: null })),
    );
    renderApp("/workspace");
    expect(await screen.findByText(/Profiles remaining: unlimited/)).toBeTruthy();
  });

  it("opens the card for a profile and the run page for the others", async () => {
    mocks.listRuns.mockResolvedValue(ok({ items: rows }));
    mocks.getOrganisation.mockResolvedValue(ok(organisation()));
    const user = userEvent.setup();
    renderApp("/workspace");
    await user.click(await screen.findByRole("link", { name: "Supplier 7" }));
    expect(where()).toBe("/profiles/run-completed");
    // The card opens beside the list, which stays.
    expect(await screen.findByRole("dialog", { name: "Supplier card" })).toBeTruthy();
    expect(screen.getByRole("table")).toBeTruthy();
  });

  it("opens the run page for a run still going", async () => {
    mocks.listRuns.mockResolvedValue(ok({ items: rows }));
    mocks.getOrganisation.mockResolvedValue(ok(organisation()));
    const user = userEvent.setup();
    renderApp("/workspace");
    await user.click(await screen.findByRole("link", { name: "Supplier 1" }));
    expect(where()).toBe("/profiles/run-running/run");
  });

  it("shows long and non-Latin names as they are", async () => {
    const names = ["東京精密工業株式会社", "Société Générale d'Étude Ünïcode ".repeat(6)];
    mocks.listRuns.mockResolvedValue(
      ok({
        items: names.map((name, i) => run(`r${i}`, name, "completed", "2026-10-01T00:00:00Z")),
      }),
    );
    mocks.getOrganisation.mockResolvedValue(ok(organisation()));
    renderApp("/workspace");
    expect(await screen.findByRole("link", { name: names[0] as string })).toBeTruthy();
    expect(screen.getByRole("link", { name: (names[1] as string).trim() })).toBeTruthy();
  });

  it("shows an empty state with a call to start the first profile", async () => {
    mocks.listRuns.mockResolvedValue(ok({ items: [] }));
    mocks.getOrganisation.mockResolvedValue(ok(organisation({ profiles_remaining: 9 })));
    const user = userEvent.setup();
    const view = renderApp("/workspace");
    await screen.findByRole("heading", { name: "No profile yet" });
    await expectNoCriticalIssues(view.container);
    await user.click(screen.getByRole("link", { name: "Start your first profile" }));
    expect(where()).toBe("/profiles/new");
  });

  it("shows a plain error with a retry, never a blank page", async () => {
    mocks.listRuns.mockResolvedValueOnce(fail("unavailable", 503));
    mocks.listRuns.mockResolvedValueOnce(ok({ items: rows }));
    mocks.getOrganisation.mockResolvedValue(ok(organisation()));
    const user = userEvent.setup();
    renderApp("/workspace");
    expect((await screen.findByRole("alert")).textContent).toMatch(/could not be loaded/);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("table")).toBeTruthy();
  });

  it("keeps the list when the organisation cannot be read: no quota, no refusal", async () => {
    mocks.listRuns.mockResolvedValue(ok({ items: rows }));
    mocks.getOrganisation.mockResolvedValue(fail("unavailable", 503));
    renderApp("/workspace");
    await screen.findByRole("table");
    expect(screen.queryByText(/Profiles remaining/)).toBeNull();
    expect(screen.getByRole("link", { name: "New profile" })).toBeTruthy();
  });
});

describe("workspace comparison", () => {
  it("keeps compare disabled with its reason until two profiles are ticked, then opens the comparison", async () => {
    mocks.listRuns.mockResolvedValue(ok({ items: rows }));
    mocks.getOrganisation.mockResolvedValue(ok(organisation()));
    const user = userEvent.setup();
    renderApp("/workspace");
    await screen.findByRole("table");
    const compare = screen.getByRole("button", { name: "Compare selected" });
    expect(compare.getAttribute("aria-disabled")).toBe("true");
    expect(compare.getAttribute("aria-describedby")).toBeTruthy();
    expect(screen.getByText(/Tick two or more/)).toBeTruthy();

    await user.click(screen.getByRole("checkbox", { name: "Select Supplier 7 for comparison" }));
    await user.click(compare);
    expect(where()).toBe("/workspace");

    await user.click(screen.getByRole("checkbox", { name: "Select Supplier 6 for comparison" }));
    expect(screen.getByText("2 profiles selected")).toBeTruthy();
    expect(compare.getAttribute("aria-disabled")).toBeNull();
    await user.click(compare);
    expect(where()).toBe("/compare?runs=run-completed,run-partial");
  });

  it("cannot tick a run that has no profile, and works by keyboard alone", async () => {
    mocks.listRuns.mockResolvedValue(ok({ items: rows }));
    mocks.getOrganisation.mockResolvedValue(ok(organisation()));
    const user = userEvent.setup();
    renderApp("/workspace");
    await screen.findByRole("table");
    const queued = screen.getByRole("checkbox", { name: "Select Supplier 0 for comparison" });
    expect((queued as HTMLInputElement).disabled).toBe(true);
    const done = screen.getByRole("checkbox", { name: "Select Supplier 7 for comparison" });
    done.focus();
    await user.keyboard(" ");
    expect((done as HTMLInputElement).checked).toBe(true);
  });
});

describe("workspace refusal", () => {
  const reasons = [
    ["quota_reached", /used its profile quota/],
    ["access_ended", /access has ended/],
    ["not_activated", /not activated yet/],
    ["spend_cap_reached", /monthly limit/],
  ] as const;

  for (const [reason, text] of reasons) {
    it(`disables New profile and explains ${reason}; existing profiles stay open`, async () => {
      mocks.listRuns.mockResolvedValue(ok({ items: rows }));
      mocks.getOrganisation.mockResolvedValue(ok(organisation({ run_refusal_reason: reason })));
      const user = userEvent.setup();
      const view = renderApp("/workspace");
      await screen.findByRole("table");
      const button = screen.getByRole("button", { name: "New profile" });
      expect(button.getAttribute("aria-disabled")).toBe("true");
      expect(screen.queryByRole("link", { name: "New profile" })).toBeNull();
      const described = document.getElementById(button.getAttribute("aria-describedby") ?? "");
      expect(described?.textContent).toMatch(text);
      expect(screen.getByText(/remain readable/)).toBeTruthy();
      await user.click(button);
      expect(where()).toBe("/workspace");
      await expectNoCriticalIssues(view.container);
      await user.click(screen.getByRole("link", { name: "Supplier 7" }));
      expect(where()).toBe("/profiles/run-completed");
    });
  }

  it("does not offer the first-profile call to action when runs are refused", async () => {
    mocks.listRuns.mockResolvedValue(ok({ items: [] }));
    mocks.getOrganisation.mockResolvedValue(
      ok(organisation({ run_refusal_reason: "access_ended" })),
    );
    renderApp("/workspace");
    await screen.findByRole("heading", { name: "No profile yet" });
    expect(screen.queryByRole("link", { name: "Start your first profile" })).toBeNull();
  });
});

describe("workspace in French and accessibility", () => {
  it("renders in French with no critical accessibility issue", async () => {
    const { initI18n } = await import("../i18n");
    await initI18n("fr");
    mocks.listRuns.mockResolvedValue(ok({ items: rows }));
    mocks.getOrganisation.mockResolvedValue(
      ok(organisation({ run_refusal_reason: "quota_reached" })),
    );
    const view = renderApp("/workspace");
    await screen.findByRole("table");
    expect(screen.getByText("Terminée")).toBeTruthy();
    expect(screen.getAllByText("27/10/2026").length).toBe(8);
    expect(screen.getByRole("button", { name: "Nouveau profil" })).toBeTruthy();
    expect(screen.getByText(/Profils restants : 4 sur 9/)).toBeTruthy();
    await expectNoCriticalIssues(view.container);
  });

  it("renders the filled state with no critical issue", async () => {
    mocks.listRuns.mockResolvedValue(ok({ items: rows }));
    mocks.getOrganisation.mockResolvedValue(ok(organisation()));
    const view = renderApp("/workspace");
    await screen.findByRole("table");
    await expectNoCriticalIssues(view.container);
  });
});

describe("safeNext", () => {
  it("rejects control characters, external and public targets", () => {
    expect(safeNext("/workspace?x=1")).toBe("/workspace?x=1");
    for (const bad of [
      "/%09/evil",
      "/\t/evil",
      "/a\nb",
      "/a\u0000b",
      "//evil",
      "/a\\b",
      "https://x",
      "/login",
    ]) {
      expect(safeNext(bad === "/%09/evil" ? decodeURIComponent(bad) : bad)).toBeNull();
    }
  });
});
