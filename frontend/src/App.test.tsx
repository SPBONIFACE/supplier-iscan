import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LANGUAGE_STORAGE_KEY } from "./i18n";
import { admin, expectNoCriticalIssues, fail, member, ok, renderApp } from "./test/utils";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  logout: vi.fn(),
  getCurrentUser: vi.fn(),
  checkInvitation: vi.fn(),
  acceptInvitation: vi.fn(),
  getDisclosure: vi.fn(),
  listRuns: vi.fn(),
  getOrganisation: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
}));

vi.mock("./lib/api", () => ({
  api: {
    login: mocks.login,
    logout: mocks.logout,
    getCurrentUser: mocks.getCurrentUser,
    checkInvitation: mocks.checkInvitation,
    acceptInvitation: mocks.acceptInvitation,
    getDisclosure: mocks.getDisclosure,
    listRuns: mocks.listRuns,
    getOrganisation: mocks.getOrganisation,
  },
  setUnauthorizedHandler: mocks.setUnauthorizedHandler,
}));

const where = () => screen.getByTestId("where").textContent;
const signedOut = () => mocks.getCurrentUser.mockResolvedValue(fail("unauthorized", 401));
const signedInAs = (user = member) => mocks.getCurrentUser.mockResolvedValue(ok(user));
const invitation = {
  email: "j.lefort@atelier-nord.example",
  organisation_name: "Atelier Nord Industrie",
  expires_at: "2026-11-04T18:00:00Z",
};

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.getDisclosure.mockResolvedValue(ok({ language: "en", text: "disclosure" }));
  mocks.listRuns.mockResolvedValue(ok({ items: [] }));
  mocks.getOrganisation.mockResolvedValue(fail("unavailable", 503));
});

describe("login", () => {
  it("takes a member to the workspace", async () => {
    signedOut();
    mocks.login.mockResolvedValue(ok(member));
    const user = userEvent.setup();
    renderApp("/login");
    await user.type(await screen.findByLabelText("Email"), "marie@example.org");
    await user.type(screen.getByLabelText("Password"), "correct horse");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Profiles" })).toBeTruthy();
    expect(where()).toBe("/workspace");
    expect(mocks.login).toHaveBeenCalledWith("marie@example.org", "correct horse");
  });

  it("takes an administrator to the administrator area", async () => {
    signedOut();
    mocks.login.mockResolvedValue(ok(admin));
    const user = userEvent.setup();
    renderApp("/login");
    await user.type(await screen.findByLabelText("Email"), "root@example.org");
    await user.type(screen.getByLabelText("Password"), "x");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Administration" })).toBeTruthy();
    expect(where()).toBe("/admin");
  });

  it("shows one generic message for a wrong password or an unknown email, keeps the email", async () => {
    signedOut();
    mocks.login.mockResolvedValue(fail("unauthorized", 401));
    const user = userEvent.setup();
    renderApp("/login");
    await user.type(await screen.findByLabelText("Email"), "a@example.org");
    await user.type(screen.getByLabelText("Password"), "nope");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Error: the email or the password is incorrect.");
    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("a@example.org");
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
    expect(document.activeElement).toBe(screen.getByLabelText("Password"));
  });

  it("flags an empty field inline and sends no request", async () => {
    signedOut();
    const user = userEvent.setup();
    renderApp("/login");
    await user.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(screen.getByText("Error: enter your email.")).toBeTruthy();
    expect(screen.getByLabelText("Email").getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(screen.getByLabelText("Email"));
    expect(mocks.login).not.toHaveBeenCalled();
  });

  it("shows a plain message when the API is unreachable or answers 503", async () => {
    signedOut();
    mocks.login.mockResolvedValue(fail("unavailable", 503));
    const user = userEvent.setup();
    renderApp("/login");
    await user.type(await screen.findByLabelText("Email"), "a@example.org");
    await user.type(screen.getByLabelText("Password"), "x");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toContain("not available right now");
  });
});

describe("session", () => {
  it("sends a signed-out user to login and back to the page asked for", async () => {
    signedOut();
    mocks.login.mockResolvedValue(ok(member));
    const user = userEvent.setup();
    renderApp("/profiles/new");
    await screen.findByRole("heading", { name: "Sign in" });
    expect(where()).toBe("/login?next=%2Fprofiles%2Fnew");
    await user.type(screen.getByLabelText("Email"), "marie@example.org");
    await user.type(screen.getByLabelText("Password"), "x");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "New profile" })).toBeTruthy();
    expect(where()).toBe("/profiles/new");
  });

  it("does not follow a return target outside the application", async () => {
    signedOut();
    mocks.login.mockResolvedValue(ok(member));
    const user = userEvent.setup();
    renderApp("/login?next=%2F%2Fevil.example");
    await user.type(await screen.findByLabelText("Email"), "m@example.org");
    await user.type(screen.getByLabelText("Password"), "x");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("heading", { name: "Profiles" });
    expect(where()).toBe("/workspace");
  });

  it("goes to login with the current page when any call answers 401", async () => {
    signedInAs();
    renderApp("/workspace");
    await screen.findByRole("heading", { name: "Profiles" });
    const handler = mocks.setUnauthorizedHandler.mock.calls.at(-1)?.[0] as () => void;
    act(() => handler());
    await screen.findByRole("heading", { name: "Sign in" });
    expect(where()).toBe("/login?next=%2Fworkspace");
  });

  it("signs out to the login screen and shows no protected page afterwards", async () => {
    signedInAs();
    mocks.logout.mockResolvedValue(ok(null));
    const user = userEvent.setup();
    renderApp("/workspace");
    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    await screen.findByRole("heading", { name: "Sign in" });
    expect(where()).toBe("/login");
    expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
    expect(screen.queryByText(/profile list/)).toBeNull();
  });
});

describe("invitation", () => {
  const open = async () => {
    signedOut();
    mocks.checkInvitation.mockResolvedValue(ok(invitation));
    const user = userEvent.setup();
    renderApp("/invitations/tok-123");
    await user.click(await screen.findByRole("button", { name: "Set your password" }));
    return user;
  };

  it("checks the token, shows the landing, then signs in directly and lands in the workspace", async () => {
    mocks.acceptInvitation.mockResolvedValue(ok(member));
    const user = await open();
    expect(mocks.checkInvitation).toHaveBeenCalledWith("tok-123");
    await user.type(screen.getByLabelText("Password"), "long enough password");
    await user.type(screen.getByLabelText("Confirm password"), "long enough password");
    await user.click(screen.getByRole("button", { name: "Set password and sign in" }));
    expect(await screen.findByRole("heading", { name: "Profiles" })).toBeTruthy();
    expect(where()).toBe("/workspace");
    expect(mocks.acceptInvitation).toHaveBeenCalledWith("tok-123", "long enough password");
    expect(mocks.login).not.toHaveBeenCalled();
  });

  it("shows the landing details with the date in the active format", async () => {
    signedOut();
    mocks.checkInvitation.mockResolvedValue(ok(invitation));
    renderApp("/invitations/tok-123");
    await screen.findByRole("heading", { name: "Join Atelier Nord Industrie on Supplier iScan" });
    expect(screen.getByText(/Nov 4, 2026, 18:00 UTC/)).toBeTruthy();
  });

  it("shows one shared message for an invalid token, without account detail", async () => {
    signedOut();
    mocks.checkInvitation.mockResolvedValue(fail("not_found", 404));
    renderApp("/invitations/old");
    await screen.findByRole("heading", { name: "This invitation link cannot be used" });
    expect(screen.queryByText(/@/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Set your password" })).toBeNull();
  });

  it("flags mismatching and empty passwords inline without a request", async () => {
    const user = await open();
    await user.type(screen.getByLabelText("Password"), "abc");
    await user.type(screen.getByLabelText("Confirm password"), "abd");
    await user.click(screen.getByRole("button", { name: "Set password and sign in" }));
    expect(screen.getByText("Error: the two passwords do not match.")).toBeTruthy();
    expect(screen.getByLabelText("Confirm password").getAttribute("aria-invalid")).toBe("true");
    expect(mocks.acceptInvitation).not.toHaveBeenCalled();
  });

  it("flags a password below the minimum (422) inline", async () => {
    mocks.acceptInvitation.mockResolvedValue(
      fail("validation", 422, [{ field: "password", message: "x" }]),
    );
    const user = await open();
    await user.type(screen.getByLabelText("Password"), "abc");
    await user.type(screen.getByLabelText("Confirm password"), "abc");
    await user.click(screen.getByRole("button", { name: "Set password and sign in" }));
    expect(await screen.findByText(/the password is too short/)).toBeTruthy();
    expect(screen.getByLabelText("Password").getAttribute("aria-invalid")).toBe("true");
  });

  it("shows the seat limit as the reason when acceptance is refused (409)", async () => {
    mocks.acceptInvitation.mockResolvedValue(fail("conflict", 409));
    const user = await open();
    await user.type(screen.getByLabelText("Password"), "long enough password");
    await user.type(screen.getByLabelText("Confirm password"), "long enough password");
    await user.click(screen.getByRole("button", { name: "Set password and sign in" }));
    expect(await screen.findByRole("heading", { name: "No seat available" })).toBeTruthy();
  });

  it("tells a signed-in user to sign out first", async () => {
    signedInAs();
    renderApp("/invitations/tok-123");
    expect(await screen.findByText("Sign out before you open an invitation link.")).toBeTruthy();
    expect(mocks.checkInvitation).not.toHaveBeenCalled();
  });

  it("never writes the token to browser storage or the console", async () => {
    const log = vi.spyOn(console, "log");
    const error = vi.spyOn(console, "error");
    const warn = vi.spyOn(console, "warn");
    mocks.acceptInvitation.mockResolvedValue(ok(member));
    const user = await open();
    await user.type(screen.getByLabelText("Password"), "long enough password");
    await user.type(screen.getByLabelText("Confirm password"), "long enough password");
    await user.click(screen.getByRole("button", { name: "Set password and sign in" }));
    await screen.findByRole("heading", { name: "Profiles" });
    for (const store of [window.localStorage, window.sessionStorage]) {
      expect(JSON.stringify({ ...store })).not.toContain("tok-123");
    }
    for (const spy of [log, error, warn])
      expect(JSON.stringify(spy.mock.calls)).not.toContain("tok-123");
    vi.restoreAllMocks();
  });
});

describe("shell", () => {
  it("shows a not-found page inside the layout for an unknown route", async () => {
    signedInAs();
    renderApp("/nowhere");
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeTruthy();
  });

  it("serves the placeholder routes of the next screens", async () => {
    signedInAs();
    renderApp("/compare");
    expect(await screen.findByRole("heading", { name: "Comparison" })).toBeTruthy();
  });

  it("hides the administrator area from members", async () => {
    signedInAs(member);
    renderApp("/admin");
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeTruthy();
  });

  it("puts the skip link first in the tab order", async () => {
    signedInAs();
    const user = userEvent.setup();
    renderApp("/workspace");
    await screen.findByRole("heading", { name: "Profiles" });
    await user.tab();
    expect(document.activeElement?.textContent).toBe("Skip to content");
  });
});

describe("language", () => {
  it("switches the whole UI without a reload and remembers the choice in this browser", async () => {
    signedOut();
    const user = userEvent.setup();
    const first = renderApp("/login");
    await user.click(await screen.findByRole("button", { name: /Français/ }));
    expect(await screen.findByRole("heading", { name: "Connexion" })).toBeTruthy();
    expect(document.documentElement.lang).toBe("fr");
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("fr");
    first.unmount();
    // a later visit: the stored choice wins over the browser language
    const { initI18n, initialLanguage } = await import("./i18n");
    await initI18n(initialLanguage());
    renderApp("/login");
    expect(await screen.findByRole("heading", { name: "Connexion" })).toBeTruthy();
  });

  it("starts from the browser language on a first visit", async () => {
    const { initialLanguage } = await import("./i18n");
    vi.spyOn(window.navigator, "languages", "get").mockReturnValue(["fr-CA", "en"]);
    expect(initialLanguage()).toBe("fr");
    vi.spyOn(window.navigator, "languages", "get").mockReturnValue(["de-DE"]);
    expect(initialLanguage()).toBe("en");
    vi.restoreAllMocks();
  });
});

describe("accessibility (axe, no critical issue)", () => {
  for (const language of ["en", "fr"] as const) {
    it(`login, invitation and shell in ${language}`, async () => {
      const { initI18n } = await import("./i18n");
      await initI18n(language);

      signedOut();
      const login = renderApp("/login");
      await screen.findByLabelText(language === "en" ? "Email" : "E-mail");
      await expectNoCriticalIssues(login.container);
      login.unmount();

      mocks.checkInvitation.mockResolvedValue(ok(invitation));
      const landing = renderApp("/invitations/t");
      const start = await screen.findByRole("button", { name: /mot de passe|password/i });
      await expectNoCriticalIssues(landing.container);
      await userEvent.setup().click(start);
      await waitFor(() =>
        expect(screen.getAllByLabelText(/mot de passe|password/i).length).toBeGreaterThan(0),
      );
      await expectNoCriticalIssues(landing.container);
      landing.unmount();

      signedInAs();
      const shell = renderApp("/workspace");
      await screen.findByRole("navigation", { name: /Main|Principale/ });
      await expectNoCriticalIssues(shell.container);
    });
  }
});
