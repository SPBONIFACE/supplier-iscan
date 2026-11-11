import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import {
  CARD_PATH,
  makeAssessment,
  makeDefinition,
  makeFact,
  makeInputs,
  makeRun,
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
  downloadRunPdf: vi.fn(),
}));

vi.mock("../lib/api", () => ({ api: mocks, setUnauthorizedHandler: vi.fn() }));

const blob = new Blob(["%PDF-1.7"], { type: "application/pdf" });
const created: string[] = [];
const clicks: { download: string; href: string }[] = [];

beforeEach(async () => {
  vi.clearAllMocks();
  created.length = 0;
  clicks.length = 0;
  await i18n.changeLanguage("en");
  mocks.getCurrentUser.mockResolvedValue(ok(member));
  mocks.getOrganisation.mockResolvedValue(ok(null));
  mocks.listRuns.mockResolvedValue(ok({ items: [makeRun()] }));
  mocks.getRun.mockResolvedValue(ok(makeRun()));
  mocks.listRunFacts.mockResolvedValue(
    ok({ items: [makeFact("legal_form", "company_overview", { value: "SAS" })] }),
  );
  mocks.getProfileDefinition.mockImplementation(async (language: "en" | "fr") =>
    ok(makeDefinition(language)),
  );
  mocks.getRunAssessment.mockResolvedValue(ok(makeAssessment()));
  mocks.getRunBuyerInputs.mockResolvedValue(ok(makeInputs()));
  URL.createObjectURL = vi.fn(() => {
    created.push("blob:test");
    return "blob:test";
  });
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicks.push({ download: this.download, href: this.href });
  });
});

describe("Download PDF on the supplier card", () => {
  it("downloads the PDF in the UI language with the file name of the server", async () => {
    const user = userEvent.setup();
    mocks.downloadRunPdf.mockResolvedValue(
      ok({ blob, filename: "supplier-card-corvane-20261105.pdf" }),
    );
    const { container } = renderApp(CARD_PATH);
    const panel = await screen.findByRole("article", { name: "Corvane Précision SAS" });

    await user.click(within(panel).getByRole("button", { name: "Download PDF" }));

    await waitFor(() => expect(clicks).toHaveLength(1));
    expect(mocks.downloadRunPdf).toHaveBeenCalledWith(expect.any(String), "en");
    expect(clicks[0]?.download).toBe("supplier-card-corvane-20261105.pdf");
    expect(clicks[0]?.href).toBe("blob:test");
    expect(await within(panel).findByText("The PDF has been downloaded.")).toBeTruthy();
    await expectNoSeriousIssues(container);
  });

  it("asks for the French file when the interface is in French", async () => {
    const user = userEvent.setup();
    await i18n.changeLanguage("fr");
    mocks.downloadRunPdf.mockResolvedValue(ok({ blob, filename: "supplier-card-x.pdf" }));
    renderApp(CARD_PATH);
    const panel = await screen.findByRole("article");

    await user.click(await within(panel).findByRole("button", { name: "Télécharger le PDF" }));

    await waitFor(() =>
      expect(mocks.downloadRunPdf).toHaveBeenCalledWith(expect.any(String), "fr"),
    );
  });

  it("shows a generating state, ignores a second click, and is operable with the keyboard", async () => {
    const user = userEvent.setup();
    let finish: (value: unknown) => void = () => {};
    mocks.downloadRunPdf.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    renderApp(CARD_PATH);
    const panel = await screen.findByRole("article", { name: "Corvane Précision SAS" });
    const button = within(panel).getByRole("button", { name: "Download PDF" });

    button.focus();
    await user.keyboard("{Enter}");

    const busy = await within(panel).findByRole("button", { name: "Generating the PDF…" });
    expect(busy.getAttribute("aria-disabled")).toBe("true");
    expect(busy.getAttribute("aria-busy")).toBe("true");
    await user.click(busy);
    expect(mocks.downloadRunPdf).toHaveBeenCalledTimes(1);
    expect(within(panel).getAllByText("Generating the PDF…").length).toBeGreaterThan(0);

    finish(ok({ blob, filename: "a.pdf" }));
    await waitFor(() => expect(clicks).toHaveLength(1));
  });

  it("shows a plain error message when the PDF fails and lets the member try again", async () => {
    const user = userEvent.setup();
    mocks.downloadRunPdf.mockResolvedValueOnce(fail("unavailable", 503));
    mocks.downloadRunPdf.mockResolvedValue(ok({ blob, filename: "a.pdf" }));
    renderApp(CARD_PATH);
    const panel = await screen.findByRole("article", { name: "Corvane Précision SAS" });

    await user.click(within(panel).getByRole("button", { name: "Download PDF" }));
    expect((await within(panel).findByRole("alert")).textContent).toMatch(
      /the PDF could not be generated/,
    );
    expect(clicks).toHaveLength(0);

    await user.click(within(panel).getByRole("button", { name: "Download PDF" }));
    await waitFor(() => expect(clicks).toHaveLength(1));
    expect(within(panel).queryByRole("alert")).toBeNull();
  });

  it("is unavailable, with the reason shown, while the run is in progress", async () => {
    mocks.getRun.mockResolvedValue(ok(makeRun({ status: "running", finished_at: null })));
    renderApp(CARD_PATH);
    const panel = await screen.findByRole("article");

    const button = await within(panel).findByRole("button", { name: "Download PDF" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(button.getAttribute("aria-describedby")).toBeTruthy();
    expect(within(panel).getByText("Available when the run has finished.")).toBeTruthy();
    expect(mocks.downloadRunPdf).not.toHaveBeenCalled();
  });
});
