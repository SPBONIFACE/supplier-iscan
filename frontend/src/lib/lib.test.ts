import { afterEach, describe, expect, it, vi } from "vitest";
import en from "../i18n/locales/en.json";
import fr from "../i18n/locales/fr.json";
import { api, setUnauthorizedHandler } from "./api";
import { formatDate, formatDateTime, formatNumber } from "./format";

// Every application source file by path, as text (Vite glob import; no Node API needed).
const files = import.meta.glob<string>("/src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
});
const sources = Object.entries(files)
  .filter(([path]) => !path.endsWith(".d.ts"))
  .map(([path, text]) => ({ path, text }));
const application = sources.filter(
  ({ path }) => !path.includes(".test.") && !path.includes("/test/"),
);

const flatten = (node: unknown, prefix = ""): string[] =>
  typeof node === "object" && node !== null
    ? Object.entries(node).flatMap(([key, value]) =>
        flatten(value, prefix ? `${prefix}.${key}` : key),
      )
    : [prefix];

describe("translations", () => {
  it("has exactly the same keys in English and French", () => {
    expect(flatten(fr).sort()).toEqual(flatten(en).sort());
  });

  it("has no empty value", () => {
    for (const key of [...flatten(en), ...flatten(fr)]) expect(key).not.toBe("");
    const values = (node: unknown): string[] =>
      typeof node === "object" && node !== null
        ? Object.values(node).flatMap(values)
        : [String(node)];
    expect(values(en).filter((v) => v.trim() === "")).toEqual([]);
    expect(values(fr).filter((v) => v.trim() === "")).toEqual([]);
  });

  it("defines every key used literally in the code", () => {
    const keys = new Set(flatten(en));
    const known = (key: string) =>
      keys.has(key) || keys.has(`${key}_one`) || keys.has(`${key}_other`);
    const used = application.flatMap(({ text }) =>
      [...text.matchAll(/\bt\(\s*"([a-zA-Z0-9_.]+)"|(?:titleKey|bodyKey)="([a-zA-Z0-9_.]+)"/g)].map(
        (m) => m[1] ?? m[2] ?? "",
      ),
    );
    expect(used.length).toBeGreaterThan(20);
    expect(used.filter((key) => !known(key))).toEqual([]);
  });
});

describe("locale formatting", () => {
  it("formats dates and numbers for the active locale", () => {
    expect(formatDate("2026-10-25T10:00:00Z", "fr")).toBe("25/10/2026");
    expect(formatDate("2026-10-25T10:00:00Z", "en")).toBe("Oct 25, 2026");
    expect(formatDateTime("2026-11-04T18:00:00Z", "en")).toBe("Nov 4, 2026, 18:00 UTC");
    expect(formatDateTime("2026-11-04T18:00:00Z", "fr")).toBe("04/11/2026 18:00 UTC");
    expect(formatNumber(1234.5, "en")).toBe("1,234.5");
    expect(formatNumber(1234.5, "fr").replace(/\s/g, " ")).toBe("1 234,5");
  });
});

describe("single API client", () => {
  it("is the only source file that calls fetch, XMLHttpRequest or an HTTP library", () => {
    const forbidden =
      /\b(fetch|XMLHttpRequest|sendBeacon|axios|ky|superagent|got)\s*[(.]|from\s+"(axios|ky|got|superagent|node:https?|undici)"/;
    const offenders = application
      .filter(({ path }) => !path.endsWith("/lib/api.ts"))
      .filter(({ text }) => forbidden.test(text))
      .map(({ path }) => path);
    expect(offenders).toEqual([]);
  });
});

describe("api client behaviour", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setUnauthorizedHandler(null);
  });

  const stub = (status: number, body?: unknown) =>
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(body === undefined ? null : JSON.stringify(body), {
            status,
            headers: { "content-type": "application/json" },
          }),
      ),
    );

  it("calls the handler on a 401 of a protected call, not on a failed login", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    stub(401, { detail: "Authentication required." });
    expect((await api.getCurrentUser()).ok).toBe(false);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(await api.login("a@b.c", "x")).toMatchObject({ ok: false, kind: "unauthorized" });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("maps statuses and a network error to failure kinds", async () => {
    stub(404, { detail: "Not found." });
    expect(await api.checkInvitation("t")).toMatchObject({ kind: "not_found" });
    stub(409, { detail: "Seat limit reached." });
    expect(await api.acceptInvitation("t", "p")).toMatchObject({ kind: "conflict" });
    stub(422, { detail: "x", errors: [{ field: "password", message: "short" }] });
    expect(await api.acceptInvitation("t", "p")).toMatchObject({
      kind: "validation",
      errors: [{ field: "password" }],
    });
    stub(503, { detail: "down" });
    expect(await api.getCurrentUser()).toMatchObject({ kind: "unavailable", status: 503 });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("network"))),
    );
    expect(await api.getCurrentUser()).toMatchObject({ kind: "unavailable", status: 0 });
  });

  it("sends credentials and the token only in the path", async () => {
    const calls = vi.fn(
      async (_request: Request) =>
        new Response(
          JSON.stringify({
            email: "a",
            organisation_name: "o",
            expires_at: "2026-01-01T00:00:00Z",
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    );
    vi.stubGlobal("fetch", calls);
    await api.checkInvitation("secret-token");
    const request = calls.mock.calls[0]?.[0] as Request;
    expect(request.credentials).toBe("include");
    expect(new URL(request.url).pathname).toBe("/invitations/secret-token");
  });
});
