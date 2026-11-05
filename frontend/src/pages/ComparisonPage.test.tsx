import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import type { ComparisonRun, MemberOrganisation } from "../lib/api";
import { makeDefinition, makeFact, makeNotFound, makeRun } from "../test/cardFixtures";
import { expectNoSeriousIssues, fail, member, ok, renderApp } from "../test/utils";

const mocks = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  getOrganisation: vi.fn(),
  listRuns: vi.fn(),
  getComparison: vi.fn(),
  getProfileDefinition: vi.fn(),
}));

vi.mock("../lib/api", () => ({ api: mocks, setUnauthorizedHandler: vi.fn() }));

const ID = (n: number) => `00000000-0000-4000-8000-00000000000${n}`;
const organisation = (changes: Partial<MemberOrganisation> = {}): MemberOrganisation => ({
  name: "Atelier Nord",
  status: "active",
  seat_limit: null,
  profile_quota: null,
  profiles_remaining: null,
  run_refusal_reason: null,
  access_ends_at: null,
  comparison_max_profiles: 6,
  ...changes,
});

const column = (
  n: number,
  extra: Partial<ComparisonRun["run"]> = {},
  facts = true,
): ComparisonRun => ({
  run: makeRun({ id: ID(n), supplier_name: `Supplier ${n}`, proposed_facts: n, ...extra }),
  facts: facts
    ? [
        makeFact("legal_form", "company_overview", {
          id: `f-${n}-legal`,
          value: `Form ${n}`,
          quote: `Quote ${n} 日本語の引用`,
        }),
        makeNotFound("founding_year", "company_overview"),
        makeFact("quality_management", "certifications", {
          id: `f-${n}-q`,
          status: "corrected",
          value: `ISO ${n}`,
          original_value: "ISO old",
          reviewed_at: "2026-10-27T10:00:00Z",
          reviewed_by_email: "claire@example.org",
        }),
      ]
    : [],
});

const open = (path: string, items: ComparisonRun[]) => {
  mocks.getComparison.mockResolvedValue(ok({ items }));
  return renderApp(path);
};

beforeEach(async () => {
  vi.clearAllMocks();
  await i18n.changeLanguage("en");
  mocks.getCurrentUser.mockResolvedValue(ok(member));
  mocks.getOrganisation.mockResolvedValue(ok(organisation()));
  mocks.getProfileDefinition.mockImplementation((language: "en" | "fr") =>
    Promise.resolve(ok(makeDefinition(language))),
  );
});

describe("the comparison screen", () => {
  it("shows 3 profiles as columns with status, source chip and the unchanged wording", async () => {
    const { container } = open(`/compare?runs=${ID(1)},${ID(2)},${ID(3)}`, [
      column(1),
      column(2),
      column(3),
    ]);

    const grid = await screen.findByRole("grid", { name: "Comparison of 3 profiles" });
    expect(mocks.getComparison).toHaveBeenCalledWith([ID(1), ID(2), ID(3)]);
    expect(within(grid).getByRole("heading", { name: "Supplier 2", level: 2 })).toBeTruthy();
    expect(within(grid).getByRole("rowheader", { name: "Legal form" })).toBeTruthy();
    expect(within(grid).getAllByText("No public evidence found")).toHaveLength(3);
    expect(within(grid).getAllByText("Corrected")).toHaveLength(3);
    expect(within(grid).getAllByText("Proposed")).toHaveLength(3);
    expect(within(grid).getAllByText(/Original AI value/)).toHaveLength(3);
    expect(within(grid).getAllByText(/Corrected by claire@example.org on/)).toHaveLength(3);
    expect(container.querySelector("table.matrix")).toBeNull();
    await expectNoSeriousIssues(container);
  });

  it("uses the compact matrix from 5 profiles and has no serious accessibility issue", async () => {
    const items = [1, 2, 3, 4, 5].map((n) => column(n));
    const { container } = open(`/compare?runs=${items.map((i) => i.run.id).join(",")}`, items);

    await screen.findByRole("grid", { name: "Comparison of 5 profiles" });
    expect(container.querySelector("table.matrix")).not.toBeNull();
    expect(screen.queryByText(/Corrected by claire/)).toBeNull(); // bylines stay in the card
    await expectNoSeriousIssues(container);
  });

  it("opens the Quote from the source chip with Enter and closes it with Escape", async () => {
    const user = userEvent.setup();
    open(`/compare?runs=${ID(1)},${ID(2)}`, [column(1), column(2)]);
    await screen.findByRole("grid");

    const chip = screen.getAllByRole("button", { name: /corvane-precision.example/ })[0];
    if (!chip) throw new Error("no chip");
    chip.focus();
    await user.keyboard("{Enter}");
    expect(chip.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Quote 1 日本語の引用")).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(chip.getAttribute("aria-expanded")).toBe("false");
    await waitFor(() => expect(document.activeElement).toBe(chip));
    await user.keyboard("{Escape}");
    expect((document.activeElement as HTMLElement).getAttribute("role")).toBe("gridcell");
  });

  it("is one tab stop and moves between cells with the arrow keys", async () => {
    const user = userEvent.setup();
    open(`/compare?runs=${ID(1)},${ID(2)}`, [column(1), column(2)]);
    const grid = await screen.findByRole("grid");

    const cells = within(grid).getAllByRole("gridcell");
    expect(cells.filter((cell) => cell.tabIndex === 0)).toHaveLength(1);
    cells[0]?.focus();
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(cells[1]);
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(cells[3]);
    await user.keyboard("{Home}");
    expect(document.activeElement).toBe(cells[2]);
    await user.keyboard("{Control>}{End}{/Control}");
    expect(document.activeElement).toBe(cells[cells.length - 1]);
    await user.keyboard("{Control>}{Home}{/Control}");
    expect(document.activeElement).toBe(cells[0]);
    await user.keyboard("{PageDown}");
    expect(document.activeElement).toBe(cells[6]); // first field of the next section
    await user.keyboard("{PageUp}");
    expect(document.activeElement).toBe(cells[0]);
  });

  it("shows a run in progress, a partial run and an unexamined field without 'No public evidence found'", async () => {
    const items = [
      column(1),
      column(2, { status: "running" }, false),
      column(3, { status: "partial", uncovered_sections: ["certifications"] }),
    ];
    // The partial run did not examine the certifications section: its fact is absent.
    items[2] = {
      ...items[2],
      facts: (items[2] as ComparisonRun).facts.slice(0, 2),
    } as ComparisonRun;
    open(`/compare?runs=${ID(1)},${ID(2)},${ID(3)}`, items);

    const grid = await screen.findByRole("grid");
    expect(within(grid).getAllByText("Run in progress").length).toBeGreaterThan(3);
    expect(within(grid).getAllByText("partial").length).toBe(1);
    expect(
      within(grid).getAllByText("Not covered by this run: it stopped before this field (partial)."),
    ).toHaveLength(2); // quality and environmental management
    // Only the found-nothing field of the finished runs reads "No public evidence found".
    expect(within(grid).getAllByText("No public evidence found")).toHaveLength(2);
  });

  it("says nothing about assessment for a natural-person supplier and ranks no one", async () => {
    const items = [column(1, { natural_person: true }), column(2)];
    const { container } = open(`/compare?runs=${ID(1)},${ID(2)}`, items);
    await screen.findByRole("grid");

    const text = container.textContent ?? "";
    expect(text).not.toMatch(/not assessed|score|rank|better|weak/i);
    expect(text).not.toMatch(/Not assessed: natural-person business/);
  });

  it("renders in French with French dates", async () => {
    await i18n.changeLanguage("fr");
    open(`/compare?runs=${ID(1)},${ID(2)}`, [column(1), column(2)]);

    await screen.findByRole("grid", { name: "Comparaison de 2 profils" });
    expect(screen.getAllByText("Aucune preuve publique trouvée").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Corrigé par claire@example.org le 27\/10\/2026/).length).toBe(2);
    expect(mocks.getProfileDefinition).toHaveBeenCalledWith("fr");
  });

  it("removes a column and sends the member back when fewer than 2 are left", async () => {
    const user = userEvent.setup();
    open(`/compare?runs=${ID(1)},${ID(2)}`, [column(1), column(2)]);
    await screen.findByRole("grid");

    await user.click(screen.getByRole("button", { name: "Remove Supplier 2" }));

    expect(await screen.findByText("Choose at least two profiles to compare.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Back to the profiles" })).toBeTruthy();
  });

  it("answers fewer than 2 ids without a call, and too many with the configured maximum", async () => {
    open(`/compare?runs=${ID(1)}`, []);
    expect(await screen.findByText("Choose at least two profiles to compare.")).toBeTruthy();
    expect(mocks.getComparison).not.toHaveBeenCalled();
  });

  it("shows the range message on a 422", async () => {
    mocks.getComparison.mockResolvedValue(fail("validation", 422));
    renderApp(`/compare?runs=${ID(1)},${ID(2)},${ID(3)}`);
    expect(await screen.findByText(/between 2 and 6 profiles/)).toBeTruthy();
  });

  it("shows the not-found page when an id cannot be accessed", async () => {
    mocks.getComparison.mockResolvedValue(fail("not_found", 404));
    renderApp(`/compare?runs=${ID(1)},${ID(2)}`);
    expect(await screen.findByRole("heading", { name: /not found/i })).toBeTruthy();
  });

  it("shows an error with a retry action", async () => {
    const user = userEvent.setup();
    mocks.getComparison.mockResolvedValueOnce(fail("unavailable", 503));
    mocks.getComparison.mockResolvedValue(ok({ items: [column(1), column(2)] }));
    renderApp(`/compare?runs=${ID(1)},${ID(2)}`);
    await user.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("grid")).toBeTruthy();
    expect(mocks.getComparison).toHaveBeenCalledTimes(2);
  });
});
