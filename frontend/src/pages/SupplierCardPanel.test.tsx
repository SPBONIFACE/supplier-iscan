import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Fact, ProfileDefinition, Run } from "../lib/api";
import { makeAssessment, makeInputs } from "../test/cardFixtures";
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
  listRunFailures: vi.fn(),
  listRunSources: vi.fn(),
  getDisclosure: vi.fn(),
}));

vi.mock("../lib/api", () => ({ api: mocks, setUnauthorizedHandler: vi.fn() }));

const ID = "44444444-4444-4444-8444-444444444444";
const PATH = `/profiles/${ID}`;
const where = () => screen.getByTestId("where").textContent;

const run = (changes: Partial<Run> = {}): Run =>
  ({
    id: ID,
    identity_id: "55555555-5555-4555-8555-555555555555",
    supplier_name: "Corvane Précision SAS",
    supplier_website: "https://corvane-precision.example/",
    supplier_country: "FR",
    supplier_sector: "Precision machining for aerospace",
    natural_person: false,
    status: "completed",
    stage: "assessment",
    identity_to_verify: false,
    excluded_sources: [],
    stop_requested: false,
    proposed_facts: 0,
    uncovered_sections: [],
    created_at: "2026-10-26T10:00:00Z",
    started_at: "2026-10-26T10:00:30Z",
    finished_at: "2026-10-26T10:20:00Z",
    ...changes,
  }) as Run;

const field = (
  id: string,
  label: string,
  extra: Partial<ProfileDefinition["sections"][number]["fields"][number]> = {},
) => ({
  id,
  label,
  kind: "fact" as const,
  certification: false,
  concerns_people: false,
  key_figure: false,
  ...extra,
});

const definition = (language: "en" | "fr" = "en"): ProfileDefinition => {
  const fr = language === "fr";
  return {
    hash: "sha256:x",
    language,
    sections: [
      {
        id: "company_overview",
        label: fr ? "Présentation de l'entreprise" : "Company overview",
        fields: [
          field("legal_form", fr ? "Forme juridique" : "Legal form"),
          field("founding_year", fr ? "Année de création" : "Founding year", { key_figure: true }),
          field("employee_count", fr ? "Nombre de salariés" : "Number of employees", {
            key_figure: true,
          }),
          field("management_team", fr ? "Direction" : "Management", { concerns_people: true }),
        ],
      },
      {
        id: "certifications",
        label: fr ? "Certifications" : "Certifications",
        fields: [
          field("quality_management", fr ? "Management de la qualité" : "Quality management", {
            certification: true,
            key_figure: true,
          }),
          field("environmental_management", "Environmental management", {
            certification: true,
            key_figure: true,
          }),
        ],
      },
      {
        id: "swot",
        label: "SWOT",
        fields: [field("strengths", "Strengths", { kind: "assessment" })],
      },
    ],
  };
};

const fact = (fieldId: string, section: string, changes: Partial<Fact> = {}): Fact => ({
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

const notFound = (fieldId: string, section: string): Fact =>
  fact(fieldId, section, {
    status: "not_found",
    value: null,
    quote: null,
    source_id: null,
    source_url: null,
    source_type: null,
    publisher: null,
    fetched_at: null,
  });

const facts = (): Fact[] => [
  fact("legal_form", "company_overview", { status: "approved", value: "SAS" }),
  fact("founding_year", "company_overview", { value: "1987" }),
  fact("employee_count", "company_overview", {
    value: "240 at the Vénissieux site",
    quote: "Le site de Vénissieux compte aujourd'hui 240 salariés, indique […], directeur du site.",
    quote_redacted: true,
    source_type: "third_party",
    publisher: "Le Journal de l'Industrie Rhône",
    source_url: "https://lji-rhone.example/2026/03/effectif",
    author: "[…]",
  }),
  fact("management_team", "company_overview", { value: "[…] (Président)" }),
  fact("quality_management", "certifications", {
    value: "EN 9100:2018",
    verification_url: "https://www.iafcertsearch.org/search?cert=FR-04417",
  }),
  notFound("environmental_management", "certifications"),
];

const row = (label: string) => {
  const item = screen.getAllByRole("listitem").find((li) => li.textContent?.startsWith(label));
  if (!item) throw new Error(`No row ${label}`);
  return item;
};

beforeEach(async () => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.getCurrentUser.mockResolvedValue(ok(member));
  mocks.getDisclosure.mockResolvedValue(ok({ language: "en", text: "disclosure" }));
  mocks.getOrganisation.mockResolvedValue(ok(null));
  // The progress screen is reached by one link; it only has to find nothing.
  mocks.listRunFailures.mockResolvedValue(fail("not_found", 404));
  mocks.listRunSources.mockResolvedValue(fail("not_found", 404));
  mocks.listRuns.mockResolvedValue(ok({ items: [run()] }));
  mocks.getRunAssessment.mockResolvedValue(ok(makeAssessment()));
  mocks.getRunBuyerInputs.mockResolvedValue(ok(makeInputs()));
  mocks.getRun.mockResolvedValue(ok(run()));
  mocks.listRunFacts.mockResolvedValue(ok({ items: facts() }));
  mocks.getProfileDefinition.mockImplementation(async (language: "en" | "fr") =>
    ok(definition(language)),
  );
  const { initI18n } = await import("../i18n");
  await initI18n("en");
});

describe("supplier card, content", () => {
  it("shows the header, one row per fact field with value, status, source and source type", async () => {
    const view = renderApp(PATH);
    expect(await screen.findByText("Loading…")).toBeTruthy();
    const panel = await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    expect(
      within(panel).getByRole("heading", { name: "Corvane Précision SAS", level: 1 }),
    ).toBeTruthy();
    const site = within(panel).getByRole("link", { name: /corvane-precision\.example/ });
    expect(site.getAttribute("href")).toBe("https://corvane-precision.example/");
    expect(site.getAttribute("target")).toBe("_blank");
    expect(site.getAttribute("rel")).toBe("noopener noreferrer");
    expect(within(panel).getByText("France", { selector: "dd" })).toBeTruthy();
    expect(within(panel).getByText("Precision machining for aerospace")).toBeTruthy();
    expect(within(panel).getByText("Oct 26, 2026", { selector: "dd" })).toBeTruthy();

    // Sections and field labels come from the definition; the assessment-only section has no rows here.
    expect(within(panel).getByRole("heading", { name: /Company overview/ })).toBeTruthy();
    expect(within(panel).getByRole("heading", { name: /Certifications/ })).toBeTruthy();
    expect(within(panel).queryByText("Strengths")).toBeNull();

    const year = row("Founding year");
    expect(within(year).getByText("1987")).toBeTruthy();
    expect(within(year).getByText("Proposed")).toBeTruthy();
    expect(year.textContent).toMatch(/Found in corvane-precision\.example on Oct 26, 2026/);
    expect(within(year).getByText("Supplier's own claim")).toBeTruthy();
    expect(within(row("Legal form")).getByText("Approved")).toBeTruthy();
    const employees = row("Number of employees");
    expect(within(employees).getByText("Third-party source")).toBeTruthy();
    expect(within(employees).getByText("Redacted extract")).toBeTruthy();
    await act(async () => {});
    await expectNoSeriousIssues(view.container);
  });

  it("says No public evidence found for a field with none, never a negative statement", async () => {
    renderApp(PATH);
    await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    const env = row("Environmental management");
    expect(within(env).getByText("No public evidence found")).toBeTruthy();
    expect(env.textContent).not.toMatch(/not certified|no certification|does not/i);
    expect(within(env).queryByRole("button")).toBeNull();
  });

  it("shows a certification's verification link, and the generic one when the address is unsafe", async () => {
    mocks.listRunFacts.mockResolvedValue(
      ok({
        items: [
          fact("quality_management", "certifications", {
            verification_url: "javascript:alert(1)",
          }),
        ],
      }),
    );
    renderApp(PATH);
    await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    const link = within(row("Quality management")).getByRole("link", {
      name: /Verify on IAF CertSearch/,
    });
    expect(link.getAttribute("href")).toBe("https://www.iafcertsearch.org/");
  });

  it("links the verification address given by the API", async () => {
    renderApp(PATH);
    await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    const link = within(row("Quality management")).getByRole("link", {
      name: /Verify on IAF CertSearch/,
    });
    expect(link.getAttribute("href")).toBe("https://www.iafcertsearch.org/search?cert=FR-04417");
  });

  it("shows the original AI value of a corrected fact", async () => {
    mocks.listRunFacts.mockResolvedValue(
      ok({
        items: [
          fact("founding_year", "company_overview", {
            status: "corrected",
            value: "1988",
            original_value: "1987",
          }),
        ],
      }),
    );
    renderApp(PATH);
    await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    const year = row("Founding year");
    expect(within(year).getByText("Corrected")).toBeTruthy();
    expect(year.textContent).toMatch(/Original AI value: 1987/);
  });

  it("renders supplier text as text and long, CJK and 300-character values without HTML", async () => {
    const quote = "あ".repeat(10) + "東京精密工業株式会社".repeat(25);
    const long = "Machined parts ".repeat(40);
    mocks.getRun.mockResolvedValue(
      ok(run({ supplier_name: '<img src=x onerror="alert(1)">Corvane' })),
    );
    mocks.listRunFacts.mockResolvedValue(
      ok({
        items: [
          fact("founding_year", "company_overview", {
            value: `<b>1987</b> ${long}`,
            quote,
            source_url: "javascript:alert(1)",
          }),
        ],
      }),
    );
    const user = userEvent.setup();
    const view = renderApp(PATH);
    await screen.findAllByText(/Machined parts/);
    expect(view.container.querySelector("img, b")).toBeNull();
    await user.click(within(row("Founding year")).getByRole("button", { name: /Found in/ }));
    const block = view.container.querySelector("blockquote");
    expect(block?.textContent).toBe(quote);
    expect(block?.getAttribute("lang")).toBe("ja");
    // An address that is not http or https is shown as text, never as a link.
    expect(view.container.querySelector('a[href^="javascript"]')).toBeNull();
    expect(view.container.querySelector("a[target]")).toBeTruthy(); // the header website
  });
});

describe("supplier card, source chip and quote", () => {
  it("opens with Enter or Space, shows the quote with its attribution, closes with Escape and returns focus", async () => {
    const user = userEvent.setup();
    const view = renderApp(PATH);
    await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    const chip = within(row("Number of employees")).getByRole("button", { name: /Found in/ });
    expect(chip.getAttribute("aria-expanded")).toBe("false");

    chip.focus();
    await user.keyboard("{Enter}");
    expect(chip.getAttribute("aria-expanded")).toBe("true");
    const note = screen.getByRole("region", { name: /Quote · Number of employees/ });
    const quote = note.querySelector("blockquote") as HTMLElement;
    // Verbatim, in its source language, with the omission marked.
    expect(quote.textContent).toBe(
      "Le site de Vénissieux compte aujourd'hui 240 salariés, indique […] redacted, directeur du site.",
    );
    expect(quote.querySelector(".redact")?.textContent).toMatch(/^\[…\]/);
    expect(within(note).getByText("Redacted extract")).toBeTruthy();
    expect(within(note).getByText("Third-party source")).toBeTruthy();
    expect(within(note).getByText("Publisher").nextSibling?.textContent).toBe(
      "Le Journal de l'Industrie Rhône",
    );
    const link = within(note).getByRole("link", { name: /lji-rhone\.example/ });
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(document.activeElement?.textContent).toMatch(/^Quote · Number of employees/);
    await act(async () => {});
    await expectNoSeriousIssues(view.container);

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("region", { name: /Quote ·/ })).toBeNull();
    expect(document.activeElement).toBe(chip);
    expect(where()).toBe(PATH); // Escape closed the quote, not the panel

    chip.focus();
    await user.keyboard(" ");
    expect(chip.getAttribute("aria-expanded")).toBe("true");
    await user.click(
      within(screen.getByRole("region", { name: /Quote ·/ })).getByRole("button", {
        name: "Close quote",
      }),
    );
    expect(document.activeElement).toBe(chip);
  });
});

describe("supplier card, key figures", () => {
  it("repeats the selected facts with status and chip, and says No public evidence found when missing", async () => {
    const user = userEvent.setup();
    renderApp(PATH);
    await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    const figures = document.querySelector("dl.kf") as HTMLElement;
    expect(figures.getAttribute("aria-label")).toBe("Key figures, repeating facts of this card");
    expect(within(figures).getByText("Founding year")).toBeTruthy();
    expect(within(figures).getByText("1987")).toBeTruthy();
    expect(within(figures).getByText("No public evidence found")).toBeTruthy();
    expect(within(figures).queryByText("Legal form")).toBeNull();

    const chip = within(figures).getByRole("button", {
      name: /Le Journal de l'Industrie Rhône · Oct 26, 2026/,
    });
    await user.click(chip);
    const note = screen.getAllByRole("region", {
      name: /Quote · Number of employees/,
    })[0] as HTMLElement;
    expect(note.textContent).toMatch(/Le site de Vénissieux/);
    await user.keyboard("{Escape}");
    expect(document.activeElement).toBe(chip);
  });

  it("shows no band when the definition selects no key figure", async () => {
    const plain = definition();
    for (const section of plain.sections) for (const f of section.fields) f.key_figure = false;
    mocks.getProfileDefinition.mockResolvedValue(ok(plain));
    renderApp(PATH);
    await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    expect(document.querySelector("dl.kf")).toBeNull();
  });
});

describe("supplier card, flags", () => {
  it("shows the identity to verify banner", async () => {
    mocks.getRun.mockResolvedValue(ok(run({ identity_to_verify: true })));
    renderApp(PATH);
    await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    expect(screen.getByText("identity to verify")).toBeTruthy();
    expect(
      screen.getByText(/Check that this website belongs to the company you confirmed/),
    ).toBeTruthy();
    expect(screen.queryByText("partial", { selector: ".ml" })).toBeNull();
  });

  it("shows the partial banner with the sections not covered, and never says No public evidence found of them", async () => {
    mocks.getRun.mockResolvedValue(
      ok(run({ status: "partial", uncovered_sections: ["certifications", "recommendations"] })),
    );
    mocks.listRunFacts.mockResolvedValue(
      ok({ items: facts().filter((f) => f.section === "company_overview") }),
    );
    const view = renderApp(PATH);
    await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    expect(screen.getByText("partial", { selector: ".ml" })).toBeTruthy();
    expect(
      screen.getByText(/Sections not covered: Certifications, Procurement recommendations/),
    ).toBeTruthy();
    expect(
      screen.getByText(/Not covered by this run: it stopped before this section/),
    ).toBeTruthy();
    expect(screen.queryByText("No public evidence found", { selector: ".missing" })).toBeNull();
    await act(async () => {});
    await expectNoSeriousIssues(view.container);
  });

  it("marks the fields of a partly covered section that were not examined", async () => {
    mocks.getRun.mockResolvedValue(
      ok(run({ status: "partial", uncovered_sections: ["certifications"] })),
    );
    mocks.listRunFacts.mockResolvedValue(
      ok({
        items: [
          ...facts().filter((f) => f.section === "company_overview"),
          fact("quality_management", "certifications"),
        ],
      }),
    );
    renderApp(PATH);
    await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    const env = row("Environmental management");
    expect(
      within(env).getByText(/Not covered by this run: it stopped before this field/),
    ).toBeTruthy();
    expect(within(env).queryByText("No public evidence found")).toBeNull();
  });

  it("says neutrally that the assessment is skipped for a natural person, because of the legal form", async () => {
    mocks.getRun.mockResolvedValue(ok(run({ natural_person: true })));
    renderApp(PATH);
    await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    const section = screen
      .getByRole("heading", { name: "Assessment" })
      .closest("section") as HTMLElement;
    expect(section.textContent).toMatch(/because of its legal form/);
    expect(section.textContent).toMatch(/says nothing about the supplier/);
    expect(section.textContent).not.toMatch(/risk|credit|unreliable/i);
  });
});

describe("supplier card, states", () => {
  it("points a run still going to its progress screen instead of an empty card", async () => {
    mocks.getRun.mockResolvedValue(ok(run({ status: "running", stage: "extraction" })));
    const user = userEvent.setup();
    renderApp(PATH);
    expect(await screen.findByText(/still going/)).toBeTruthy();
    expect(mocks.listRunFacts).not.toHaveBeenCalled();
    await user.click(screen.getByRole("link", { name: "See the progress of the run" }));
    expect(where()).toBe(`${PATH}/run`);
  });

  it("points a run that ended without a profile to its progress screen", async () => {
    mocks.getRun.mockResolvedValue(ok(run({ status: "insufficient_sources" })));
    renderApp(PATH);
    expect(
      await screen.findByText(/ended without a profile \(status: Insufficient sources\)/),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "See the progress of the run" })).toBeTruthy();
  });

  it("shows the not-found page for an unknown or foreign run", async () => {
    mocks.getRun.mockResolvedValue(fail("not_found", 404));
    renderApp(PATH);
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeTruthy();
  });

  it("shows an error with a retry when the API fails", async () => {
    mocks.listRunFacts.mockResolvedValueOnce(fail("unavailable", 503));
    const user = userEvent.setup();
    renderApp(PATH);
    expect((await screen.findByRole("alert")).textContent).toMatch(/could not be loaded/);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("heading", { name: "Corvane Précision SAS", level: 1 });
  });
});

describe("supplier card, panel", () => {
  it("opens beside the workspace and closes with Escape, giving focus back to the row that opened it", async () => {
    const user = userEvent.setup();
    renderApp("/workspace");
    const opener = await screen.findByRole("link", { name: "Corvane Précision SAS" });
    await user.click(opener);
    expect(where()).toBe(PATH);
    const panel = await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    expect(screen.getByRole("table")).toBeTruthy(); // the list stays
    await waitFor(() => expect(document.activeElement?.id).toBe("card-name"));
    expect(panel.contains(document.activeElement)).toBe(true);

    await user.keyboard("{Escape}");
    await waitFor(() => expect(where()).toBe("/workspace"));
    await waitFor(() => expect(document.activeElement?.getAttribute("data-run-id")).toBe(ID));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes with the Close button", async () => {
    const user = userEvent.setup();
    renderApp(PATH);
    await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    await user.click(screen.getByRole("button", { name: /^Close/ }));
    await waitFor(() => expect(where()).toBe("/workspace"));
  });
});

describe("supplier card, French", () => {
  it("follows the UI language for labels and leaves the quote unchanged", async () => {
    const { initI18n } = await import("../i18n");
    await initI18n("fr");
    const user = userEvent.setup();
    renderApp(PATH);
    const panel = await screen.findByRole("dialog", { name: "Corvane Précision SAS" });
    expect(mocks.getProfileDefinition).toHaveBeenCalledWith("fr");
    expect(within(panel).getByText("Dernière actualisation")).toBeTruthy();
    expect(within(panel).getByText("26/10/2026", { selector: "dd" })).toBeTruthy();
    expect(within(row("Nombre de salariés")).getByText("Source tierce")).toBeTruthy();
    expect(within(row("Nombre de salariés")).getByText("Extrait masqué")).toBeTruthy();
    expect(within(row("Année de création")).getByText("Déclaration du fournisseur")).toBeTruthy();
    expect(
      within(row("Environmental management")).getByText("Aucune preuve publique trouvée"),
    ).toBeTruthy();
    await user.click(
      within(row("Nombre de salariés")).getByRole("button", { name: /Trouvé dans/ }),
    );
    expect(panel.querySelector("blockquote")?.textContent).toMatch(
      /^Le site de Vénissieux compte aujourd'hui 240 salariés/,
    );
  });
});
