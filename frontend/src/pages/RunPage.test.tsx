import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MemberOrganisation, Run, RunFailure } from "../lib/api";
import { expectNoSeriousIssues, fail, member, ok, renderApp } from "../test/utils";

const mocks = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  getOrganisation: vi.fn(),
  getRun: vi.fn(),
  listRunFailures: vi.fn(),
  listRunSources: vi.fn(),
  stopRun: vi.fn(),
  resumeRun: vi.fn(),
  getProfileDefinition: vi.fn(),
  listRuns: vi.fn(),
  listRunFacts: vi.fn(),
  getDisclosure: vi.fn(),
}));

vi.mock("../lib/api", () => ({ api: mocks, setUnauthorizedHandler: vi.fn() }));

const ID = "44444444-4444-4444-8444-444444444444";
const PATH = `/profiles/${ID}/run`;

const run = (changes: Partial<Run> = {}): Run => ({
  id: ID,
  identity_id: "55555555-5555-4555-8555-555555555555",
  supplier_name: "Ardentis France SAS",
  supplier_website: "https://ardentis-france.example",
  supplier_country: "France",
  supplier_sector: "Industrial automation",
  natural_person: false,
  status: "running",
  stage: "collection",
  stop_requested: false,
  counts_against_quota: true,
  pause_dependency: null,
  pause_reason: null,
  error: null,
  profile_definition_hash: null,
  prompt_set_hash: null,
  usage: {
    calls: 0,
    input_tokens: 0,
    output_tokens: 0,
    reasoning_tokens: 0,
    tool_calls: 0,
    cost: "0",
    roles: [],
  },
  excluded_sources: [],
  identity_to_verify: false,
  grounding_failures: 0,
  invalid_items: 0,
  uncovered_sections: [],
  partial_explanation: null,
  proposed_facts: 0,
  insufficient_sources_explanation: null,
  created_at: "2026-10-27T14:07:00Z",
  started_at: "2026-10-27T14:07:30Z",
  finished_at: null,
  ...changes,
});

const failure = (changes: Partial<RunFailure> = {}): RunFailure => ({
  id: "66666666-6666-4666-8666-666666666666",
  url: "https://ardentis-france.example/fr/rse",
  strategy: "website",
  kind: "http_error",
  next_strategy: "sitemap",
  message: "HTTP 404",
  created_at: "2026-10-27T14:08:12Z",
  ...changes,
});

const organisation = (changes: Partial<MemberOrganisation> = {}): MemberOrganisation => ({
  name: "Corvane Group",
  status: "active",
  seat_limit: null,
  profile_quota: 9,
  profiles_remaining: 4,
  run_refusal_reason: null,
  access_ends_at: null,
  comparison_max_profiles: 10,
  ...changes,
});

const sources = (count: number) => ({
  items: Array.from({ length: count }, (_, index) => ({
    id: `s${index}`,
    url: `https://ardentis-france.example/${index}`,
    fetched_at: "2026-10-27T14:08:00Z",
    content_type: "text/html",
  })),
});

const where = () => screen.getByTestId("where").textContent;

beforeEach(async () => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  vi.stubEnv("VITE_RUN_POLL_INTERVAL_MS", "100");
  mocks.getCurrentUser.mockResolvedValue(ok(member));
  mocks.getDisclosure.mockResolvedValue(ok({ language: "en", text: "disclosure" }));
  mocks.getOrganisation.mockResolvedValue(ok(organisation()));
  // The card and the list open from the run screen; they only have to find nothing.
  mocks.listRuns.mockResolvedValue(fail("unavailable", 503));
  mocks.listRunFacts.mockResolvedValue(fail("unavailable", 503));
  mocks.listRunFailures.mockResolvedValue(ok({ items: [] }));
  mocks.listRunSources.mockResolvedValue(ok(sources(0)));
  mocks.getProfileDefinition.mockResolvedValue(
    ok({
      hash: "sha256:x",
      language: "en",
      sections: [
        { id: "financial", label: "Financial health", fields: [] },
        { id: "esg", label: "Sustainability", fields: [] },
      ],
    }),
  );
  const { initI18n } = await import("../i18n");
  await initI18n("en");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("run progress, running", () => {
  it("shows a loading indicator, then the stages with the current one named in text", async () => {
    mocks.getRun.mockResolvedValue(
      ok(run({ excluded_sources: [{ domain: "ardentis-presse.example", message: "x" }] })),
    );
    mocks.listRunSources.mockResolvedValue(ok(sources(16)));
    mocks.listRunFailures.mockResolvedValue(ok({ items: [failure()] }));
    const view = renderApp(PATH);
    expect(await screen.findByText("Loading…")).toBeTruthy();
    await screen.findByRole("heading", { name: "Ardentis France SAS", level: 1 });

    expect(screen.getByText("Stage 2 of 4: collection in progress.")).toBeTruthy();
    const stages = screen.getAllByRole("listitem").filter((li) => li.className === "stage");
    expect(stages).toHaveLength(4);
    expect(stages[0]?.textContent).toMatch(/Identity.*Done/);
    expect(stages[1]?.getAttribute("aria-current")).toBe("step");
    expect(stages[1]?.textContent).toMatch(/Collection.*In progress/);
    expect(stages[1]?.textContent).toMatch(
      /16 sources collected so far · 1 domain excluded · 1 failure logged/,
    );
    expect(stages[2]?.textContent).toMatch(/Waiting/);
    expect(screen.getByText(/Status: Running/)).toBeTruthy();
    expect(await screen.findByText("Profiles remaining: 4 of 9")).toBeTruthy();
    // The excluded domain carries the approved label; the failure is in plain language.
    expect(screen.getByText("source excluded at the site owner's request")).toBeTruthy();
    expect(screen.getByText("ardentis-presse.example")).toBeTruthy();
    const table = screen.getByRole("table", { name: "Failure log" });
    expect(within(table).getByText("https://ardentis-france.example/fr/rse")).toBeTruthy();
    expect(within(table).getByText("Website crawl")).toBeTruthy();
    expect(within(table).getByText("The server answered with an error")).toBeTruthy();
    expect(within(table).getByText("Sitemap discovery")).toBeTruthy();
    await expectNoSeriousIssues(view.container);
  });

  it("says unlimited when no quota is set, and says so when there is no failure", async () => {
    mocks.getRun.mockResolvedValue(ok(run()));
    mocks.getOrganisation.mockResolvedValue(
      ok(organisation({ profile_quota: null, profiles_remaining: null })),
    );
    renderApp(PATH);
    expect(await screen.findByText("Profiles remaining: unlimited")).toBeTruthy();
    expect(screen.getByText(/No failures/)).toBeTruthy();
  });

  it("does not claim there are no failures when the log could not be read", async () => {
    mocks.getRun.mockResolvedValue(ok(run()));
    mocks.listRunFailures.mockResolvedValue(fail("unavailable", 503));
    renderApp(PATH);
    await screen.findByText(/The failure log could not be loaded/);
    expect(screen.queryByText(/No failures/)).toBeNull();
  });

  it("polls while the run goes on, announces the stage change, and stops when it ends", async () => {
    mocks.getRun.mockResolvedValue(ok(run()));
    renderApp(PATH);
    await screen.findByText("Stage 2 of 4: collection in progress.");
    const summary = screen.getByText("Stage 2 of 4: collection in progress.");
    expect(summary.getAttribute("role")).toBe("status");
    mocks.getRun.mockResolvedValue(ok(run({ stage: "extraction" })));
    await screen.findByText("Stage 3 of 4: extraction in progress.");
    mocks.getRun.mockResolvedValue(
      ok(run({ status: "completed", stage: "assessment", finished_at: "2026-10-27T14:20:00Z" })),
    );
    await screen.findByText("All 4 stages are done.");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Stop the run" })).toBeNull());
    // Once final, no further read (one last read at the end is allowed).
    await new Promise((resolve) => setTimeout(resolve, 150));
    const settled = mocks.getRun.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(mocks.getRun.mock.calls.length).toBe(settled);
  });

  it("keeps the last state with a notice when a poll fails, then recovers", async () => {
    mocks.getRun.mockResolvedValueOnce(ok(run()));
    mocks.getRun.mockResolvedValueOnce(fail("unavailable", 0));
    mocks.getRun.mockResolvedValue(ok(run({ stage: "extraction" })));
    renderApp(PATH);
    await screen.findByText("Stage 2 of 4: collection in progress.");
    await screen.findByText(/The server cannot be reached/);
    expect(screen.getByRole("heading", { name: "Ardentis France SAS", level: 1 })).toBeTruthy();
    await screen.findByText("Stage 3 of 4: extraction in progress.");
    await waitFor(() => expect(screen.queryByText(/The server cannot be reached/)).toBeNull());
  });

  it("stops polling when the screen is left", async () => {
    mocks.getRun.mockResolvedValue(ok(run()));
    const view = renderApp(PATH);
    await screen.findByText("Stage 2 of 4: collection in progress.");
    view.unmount();
    await new Promise((resolve) => setTimeout(resolve, 50));
    const calls = mocks.getRun.mock.calls.length;
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    expect(mocks.getRun.mock.calls.length).toBe(calls);
  });

  it("shows an error with a retry when the first load fails", async () => {
    mocks.getRun.mockResolvedValueOnce(fail("unavailable", 503));
    mocks.getRun.mockResolvedValue(ok(run()));
    const user = userEvent.setup();
    renderApp(PATH);
    expect((await screen.findByRole("alert")).textContent).toMatch(/could not be loaded/);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText("Stage 2 of 4: collection in progress.");
  });

  it("shows the not-found page for an unknown or foreign run", async () => {
    mocks.getRun.mockResolvedValue(fail("not_found", 404));
    renderApp(PATH);
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeTruthy();
  });

  it("shows supplier text as text, never as HTML", async () => {
    const hostile = '<img src=x onerror="alert(1)"><b>Bold</b>';
    mocks.getRun.mockResolvedValue(
      ok(
        run({
          supplier_name: hostile,
          excluded_sources: [{ domain: "<i>evil</i>.example", message: "x" }],
        }),
      ),
    );
    mocks.listRunFailures.mockResolvedValue(
      ok({ items: [failure({ url: "javascript:alert(1)//<u>x</u>" })] }),
    );
    const view = renderApp(PATH);
    expect(await screen.findByRole("heading", { name: hostile, level: 1 })).toBeTruthy();
    expect(view.container.querySelector("img, b, i, u")).toBeNull();
    expect(view.container.querySelector('a[href^="javascript"]')).toBeNull();
  });

  it("renders in French with French dates", async () => {
    const { initI18n } = await import("../i18n");
    await initI18n("fr");
    mocks.getRun.mockResolvedValue(ok(run()));
    mocks.listRunFailures.mockResolvedValue(ok({ items: [failure()] }));
    renderApp(PATH);
    await screen.findByText(/^Étape 2 sur 4\s:\scollecte en cours\.$/);
    expect(screen.getByRole("heading", { name: "Journal des échecs" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Arrêter l’analyse" })).toBeTruthy();
    expect(screen.getAllByText(/27\/10\/2026 14:07 UTC/).length).toBeGreaterThan(0);
    expect(screen.getByText("Exploration du site")).toBeTruthy();
  });
});

describe("run progress, stop", () => {
  it("asks for confirmation, returns focus on cancel, then stops and shows stopped", async () => {
    mocks.getRun.mockResolvedValue(ok(run()));
    const user = userEvent.setup();
    renderApp(PATH);
    const stop = await screen.findByRole("button", { name: "Stop the run" });
    await user.click(stop);
    const dialog = screen.getByRole("alertdialog", { name: "Stop this profile run?" });
    expect(document.activeElement?.textContent).toBe("Stop this profile run?");
    await user.click(within(dialog).getByRole("button", { name: "Keep it running" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(document.activeElement).toBe(stop);
    expect(mocks.stopRun).not.toHaveBeenCalled();

    await user.click(stop);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();

    const stopped = run({ status: "stopped", finished_at: "2026-10-27T14:09:00Z" });
    let isStopped = false;
    mocks.stopRun.mockImplementation(async () => {
      isStopped = true;
      return ok(stopped);
    });
    mocks.getRun.mockImplementation(async () => ok(isStopped ? stopped : run()));
    await user.click(stop);
    await user.click(screen.getByRole("button", { name: "Yes, stop the run" }));
    await screen.findByText(/This profile run was stopped on Oct 27, 2026/);
    expect(mocks.stopRun).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Run stopped during stage 2 of 4 (collection).")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Stop the run" })).toBeNull();
    expect(screen.getByRole("link", { name: "Back to profiles" })).toBeTruthy();
  });

  it("tells the member the run had already finished (409) and shows the actual status", async () => {
    mocks.getRun.mockResolvedValue(ok(run()));
    let finished = false;
    mocks.stopRun.mockImplementation(async () => {
      finished = true;
      return fail("conflict", 409);
    });
    const user = userEvent.setup();
    renderApp(PATH);
    await user.click(await screen.findByRole("button", { name: "Stop the run" }));
    const done = run({
      status: "completed",
      stage: "assessment",
      finished_at: "2026-10-27T14:09:00Z",
    });
    mocks.getRun.mockImplementation(async () => ok(finished ? done : run()));
    await user.click(screen.getByRole("button", { name: "Yes, stop the run" }));
    await screen.findByText(/The run had already finished/);
    await screen.findByText("All 4 stages are done.");
  });

  it("shows a stop request that the worker has not yet honoured", async () => {
    mocks.getRun.mockResolvedValue(ok(run({ stop_requested: true })));
    renderApp(PATH);
    await screen.findByText(/Stop requested/);
    expect(screen.queryByRole("button", { name: "Stop the run" })).toBeNull();
  });
});

describe("run progress, paused", () => {
  const paused = () =>
    run({
      status: "paused",
      stage: "extraction",
      pause_dependency: "structuring_provider",
      pause_reason: "The structuring provider is unavailable",
    });

  it("names the failed dependency and resumes with one request on a double click", async () => {
    mocks.getRun.mockResolvedValue(ok(paused()));
    let release: (value: unknown) => void = () => {};
    mocks.resumeRun.mockReturnValue(new Promise((resolve) => (release = resolve)));
    const user = userEvent.setup();
    const view = renderApp(PATH);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/The structuring provider .* is unavailable/);
    expect(screen.getByText(/Stage 3 of 4: extraction paused/)).toBeTruthy();
    await expectNoSeriousIssues(view.container);

    const resume = screen.getByRole("button", { name: "Resume the run" });
    await user.dblClick(resume);
    expect(mocks.resumeRun).toHaveBeenCalledTimes(1);
    expect(resume.getAttribute("aria-disabled")).toBe("true");

    const queued = run({ status: "queued", stage: "extraction" });
    mocks.getRun.mockResolvedValue(ok(queued));
    await act(async () => release(ok(queued)));
    await screen.findByText(/Waiting to start/);
    expect(screen.queryByRole("button", { name: "Resume the run" })).toBeNull();
  });

  it("says when the run is no longer paused (409)", async () => {
    mocks.getRun.mockResolvedValue(ok(paused()));
    mocks.resumeRun.mockResolvedValue(fail("conflict", 409));
    const user = userEvent.setup();
    renderApp(PATH);
    await user.click(await screen.findByRole("button", { name: "Resume the run" }));
    mocks.getRun.mockResolvedValue(ok(run({ stage: "extraction" })));
    await screen.findByText(/no longer paused/);
    await screen.findByText("Stage 3 of 4: extraction in progress.");
  });
});

describe("run progress, end states", () => {
  it("insufficient sources: names the end state, keeps the log, and says it does not count", async () => {
    mocks.getRun.mockResolvedValue(
      ok(
        run({
          status: "insufficient_sources",
          counts_against_quota: false,
          insufficient_sources_explanation: "No usable public source",
          finished_at: "2026-10-27T14:15:00Z",
        }),
      ),
    );
    mocks.listRunFailures.mockResolvedValue(
      ok({
        items: [
          failure(),
          failure({
            id: "77777777-7777-4777-8777-777777777777",
            url: null,
            strategy: "retrieval",
            kind: "attempt_cap",
            next_strategy: null,
          }),
        ],
      }),
    );
    const view = renderApp(PATH);
    await screen.findByText("insufficient sources");
    expect(screen.getByText(/does not count against your organisation's quota/)).toBeTruthy();
    expect(screen.getByText(/The attempt cap was reached\./)).toBeTruthy();
    expect(screen.getByText("Web search (retrieval provider)")).toBeTruthy();
    expect(screen.getByText("None left")).toBeTruthy();
    expect(screen.getByText("No usable source after every strategy was tried")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Stop the run" })).toBeNull();
    await expectNoSeriousIssues(view.container);
  });

  it("failed: shows the reason in plain language", async () => {
    mocks.getRun.mockResolvedValue(
      ok(
        run({
          status: "failed",
          error: "The registry could not be reached.",
          finished_at: "2026-10-27T14:15:00Z",
        }),
      ),
    );
    renderApp(PATH);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/The registry could not be reached\./);
  });

  it("completed: offers the supplier card", async () => {
    mocks.getRun.mockResolvedValue(
      ok(run({ status: "completed", stage: "assessment", finished_at: "2026-10-27T14:20:00Z" })),
    );
    const user = userEvent.setup();
    renderApp(PATH);
    await user.click(await screen.findByRole("link", { name: "Open the supplier card" }));
    expect(where()).toBe(`/profiles/${ID}`);
  });

  it("partial: shows the partial label, the sections not done by name, and the card link", async () => {
    mocks.getRun.mockResolvedValue(
      ok(
        run({
          status: "partial",
          stage: "extraction",
          uncovered_sections: ["esg", "recommendations"],
          partial_explanation: "x",
          finished_at: "2026-10-27T14:20:00Z",
        }),
      ),
    );
    const view = renderApp(PATH);
    await screen.findByText("partial", { selector: ".ml" });
    await screen.findByText("Sustainability");
    expect(screen.getByText("Procurement recommendations")).toBeTruthy();
    expect(screen.getByText(/does not mean “No public evidence found”/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open the supplier card" })).toBeTruthy();
    const stages = screen.getAllByRole("listitem").filter((li) => li.className === "stage");
    expect(stages[2]?.textContent).toMatch(/Extraction.*Partial/);
    expect(stages[3]?.textContent).toMatch(/Assessment.*Not started/);
    await expectNoSeriousIssues(view.container);
  });
});
