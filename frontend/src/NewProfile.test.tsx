import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import i18n from "i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LANGUAGE_STORAGE_KEY } from "./i18n";
import { expectNoCriticalIssues, fail, member, ok, renderApp } from "./test/utils";

const mocks = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  getDisclosure: vi.fn(),
  createIdentitySession: vi.fn(),
  getIdentitySession: vi.fn(),
  sendIdentityMessage: vi.fn(),
  listIdentityCandidates: vi.fn(),
  submitIdentityWebsite: vi.fn(),
  confirmIdentity: vi.fn(),
  startRun: vi.fn(),
}));

vi.mock("./lib/api", () => ({ api: mocks, setUnauthorizedHandler: vi.fn() }));

const EN = "You are talking to an AI assistant. Its role: supplier research.";
const FR = "Vous échangez avec un assistant IA.";

const candidate = (id: string, legal_name: string, extra = {}) => ({
  id,
  legal_name,
  legal_form: "SE",
  website: "ardentis-group.example",
  country: "Germany",
  sector: "Industrial automation",
  description: "Maker of drives.",
  found_in: ["gleif", "website"],
  identifiers: [{ scheme: "LEI", value: "549300EXAMPLEARD0042" }],
  ...extra,
});
const turn = (
  id: string,
  kind: string,
  text: string,
  role = "assistant",
  cand: unknown = null,
) => ({
  id,
  role,
  kind,
  text,
  candidate: cand,
  created_at: "2026-11-02T14:05:00Z",
});
const session = (turns: unknown[], extra = {}) => ({
  id: "33333333-3333-4333-8333-333333333333",
  name: "Ardentis",
  hints: { website: null, country: null, sector: "Industrial automation" },
  profile_language: "en",
  status: "open",
  turns: [turn("t0", "disclosure", EN), ...turns],
  registries: { gleif: "ok", wikidata: "ok" },
  identity_id: null,
  created_at: "2026-11-02T14:05:00Z",
  ...extra,
});
const top = candidate("c1", "Ardentis Group SE");
const proposal = turn("t1", "proposal", "The most likely company is:", "assistant", top);
const CHAT = "/profiles/new/33333333-3333-4333-8333-333333333333";

beforeEach(async () => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  await i18n.changeLanguage("en");
  mocks.getCurrentUser.mockResolvedValue(ok(member));
  mocks.getDisclosure.mockImplementation(async (language: string) =>
    ok({ language, text: language === "fr" ? FR : EN }),
  );
});

describe("new profile form", () => {
  it("shows the disclosure first, rejects an empty name without a request, and has no critical a11y issue", async () => {
    const view = renderApp("/profiles/new");
    expect(await screen.findByText(EN, { exact: false })).toBeTruthy();
    await userEvent.type(screen.getByLabelText(/Supplier name/), "  ​ ");
    await userEvent.click(screen.getByRole("button", { name: "Search for the supplier" }));
    expect(screen.getByText("Error: enter the supplier's name.")).toBeTruthy();
    expect(mocks.createIdentitySession).not.toHaveBeenCalled();
    await expectNoCriticalIssues(view.container);
  });

  it("presets the profile language to the UI language without changing the UI language", async () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");
    await i18n.changeLanguage("fr");
    renderApp("/profiles/new");
    expect(await screen.findByText(FR, { exact: false })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Français" })).toHaveProperty("checked", true);
    await userEvent.click(screen.getByRole("radio", { name: "English" }));
    expect(document.documentElement.lang).toBe("fr");
    expect(screen.getByText(FR, { exact: false })).toBeTruthy();
    mocks.createIdentitySession.mockResolvedValue(ok(session([proposal])));
    await userEvent.type(screen.getByLabelText(/Nom du fournisseur/), "Müller 東京");
    await userEvent.click(screen.getByRole("button", { name: "Rechercher le fournisseur" }));
    await waitFor(() => expect(mocks.createIdentitySession).toHaveBeenCalled());
    expect(mocks.createIdentitySession.mock.calls[0][0]).toMatchObject({
      name: "Müller 東京",
      profile_language: "en",
      ui_language: "fr",
    });
  });

  it("does not start the chat when the disclosure cannot be loaded, and retries", async () => {
    mocks.getDisclosure.mockResolvedValueOnce(fail("unavailable", 503));
    renderApp("/profiles/new");
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByLabelText(/Supplier name/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByLabelText(/Supplier name/)).toBeTruthy();
  });

  it("shows the API message next to an invalid website", async () => {
    mocks.createIdentitySession.mockResolvedValue(
      fail("validation", 422, [{ field: "hints.website", message: "Website is not valid." }]),
    );
    renderApp("/profiles/new");
    await userEvent.type(await screen.findByLabelText(/Supplier name/), "Ardentis");
    await userEvent.type(screen.getByLabelText("Website"), "not a site");
    await userEvent.click(screen.getByRole("button", { name: "Search for the supplier" }));
    expect(await screen.findByText("Error: Website is not valid.")).toBeTruthy();
  });
});

describe("identity chat", () => {
  it("shows the disclosure, the candidate, other candidates, then confirms once and starts the run", async () => {
    mocks.getIdentitySession.mockResolvedValue(ok(session([proposal])));
    mocks.listIdentityCandidates.mockResolvedValue(
      ok({ candidates: [candidate("c2", "Ardentis France SAS", { country: "France" })] }),
    );
    mocks.confirmIdentity.mockResolvedValue(
      ok({ identity_id: "44444444-4444-4444-8444-444444444444" }),
    );
    let release: (value: unknown) => void = () => {};
    mocks.startRun.mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    const view = renderApp(CHAT);
    expect(await screen.findByText(EN)).toBeTruthy();
    expect(screen.getByRole("log")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Ardentis Group SE" })).toBeTruthy();
    await expectNoCriticalIssues(view.container);

    await userEvent.click(screen.getByRole("button", { name: "Show other candidates" }));
    await userEvent.click(
      await screen.findByRole("button", { name: "Select this company: Ardentis France SAS" }),
    );
    const confirm = screen.getByRole("button", { name: "Confirm and start the profile run" });
    await userEvent.dblClick(confirm);
    release(ok({ id: "55555555-5555-4555-8555-555555555555" }));
    await waitFor(() =>
      expect(screen.getByTestId("where").textContent).toBe(
        "/profiles/55555555-5555-4555-8555-555555555555/run",
      ),
    );
    expect(mocks.confirmIdentity).toHaveBeenCalledTimes(1);
    expect(mocks.confirmIdentity).toHaveBeenCalledWith(expect.any(String), "c2");
    expect(mocks.startRun).toHaveBeenCalledTimes(1);
  });

  it("keeps the confirmed identity when the run is refused, and says why", async () => {
    mocks.getIdentitySession.mockResolvedValue(ok(session([proposal])));
    mocks.confirmIdentity.mockResolvedValue(
      ok({ identity_id: "44444444-4444-4444-8444-444444444444" }),
    );
    mocks.startRun.mockResolvedValue({ ...fail("refused", 403), reason: "quota_reached" });
    renderApp(CHAT);
    await userEvent.click(await screen.findByRole("button", { name: "This is the company" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Confirm and start the profile run" }),
    );
    expect(await screen.findByText(/profile quota of your organisation is used up/)).toBeTruthy();
    mocks.startRun.mockResolvedValue(ok({ id: "55555555-5555-4555-8555-555555555555" }));
    await userEvent.click(screen.getByRole("button", { name: "Start the profile run" }));
    await waitFor(() => expect(mocks.startRun).toHaveBeenCalledTimes(2));
    expect(mocks.confirmIdentity).toHaveBeenCalledTimes(1);
  });

  it("sends a correction and shows an agent error as a chat message", async () => {
    mocks.getIdentitySession.mockResolvedValue(ok(session([proposal])));
    mocks.sendIdentityMessage.mockResolvedValue(
      ok(
        session([
          proposal,
          turn("t2", "text", "No, the French subsidiary.", "user"),
          turn("t3", "error", "I could not answer that. Please try again."),
        ]),
      ),
    );
    renderApp(CHAT);
    await userEvent.type(
      await screen.findByLabelText("Reply to the assistant"),
      "No, the French subsidiary.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("I could not answer that. Please try again.")).toBeTruthy();
    expect(screen.queryByText("Page not found")).toBeNull();
    expect(screen.getByRole("button", { name: "This is the company" })).toBeTruthy();
  });

  it("offers the website fallback when both registries are down, and shows why a domain is refused", async () => {
    mocks.getIdentitySession.mockResolvedValue(
      ok(
        session(
          [turn("t1", "notice", "Neither GLEIF nor Wikidata can be reached at the moment.")],
          {
            registries: { gleif: "unreachable", wikidata: "unreachable" },
          },
        ),
      ),
    );
    mocks.submitIdentityWebsite.mockResolvedValue(
      ok(
        session(
          [
            turn("t1", "notice", "Neither GLEIF nor Wikidata can be reached at the moment."),
            turn(
              "t2",
              "website_rejected",
              "the domain ardentis-fr.example does not respond.",
              "assistant",
            ),
          ],
          { registries: { gleif: "unreachable", wikidata: "unreachable" } },
        ),
      ),
    );
    renderApp(CHAT);
    expect(await screen.findByText(/Neither GLEIF nor Wikidata/)).toBeTruthy();
    await userEvent.type(screen.getByLabelText("Supplier website"), "ardentis-fr.example");
    await userEvent.click(screen.getByRole("button", { name: "Use this website" }));
    expect(
      (await screen.findAllByText(/the domain ardentis-fr.example does not respond/)).length,
    ).toBeGreaterThan(0);
    expect(screen.getByLabelText("Supplier website")).toHaveProperty("ariaInvalid", "true");
  });

  it("shows the not-found page for a session of another organisation", async () => {
    mocks.getIdentitySession.mockResolvedValue(fail("not_found", 404));
    renderApp(CHAT);
    expect(await screen.findByText("Page not found")).toBeTruthy();
  });
});
