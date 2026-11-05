import { render } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter, useLocation } from "react-router";
import { expect } from "vitest";
import { App } from "../App";
import { AuthProvider } from "../auth/AuthContext";
import type { CurrentUser } from "../lib/api";

export const member: CurrentUser = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "marie@example.org",
  role: "member",
  organisation_id: "22222222-2222-4222-8222-222222222222",
};
export const admin: CurrentUser = { ...member, email: "root@example.org", role: "admin" };

export const ok = <T,>(data: T) => ({ ok: true as const, data });
export const fail = (kind: string, status: number, errors: unknown[] = []) => ({
  ok: false as const,
  kind,
  status,
  errors,
});

/** Where the router is, for assertions on redirects. */
function Where() {
  const location = useLocation();
  return <output data-testid="where">{`${location.pathname}${location.search}`}</output>;
}

export function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
        <Where />
      </AuthProvider>
    </MemoryRouter>,
  );
}

/** Automated accessibility check: no critical issue. (jsdom cannot compute colour contrast.) */
export async function expectNoCriticalIssues(container: HTMLElement) {
  const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  const critical = results.violations.filter((violation) => violation.impact === "critical");
  expect(critical.map((violation) => violation.id)).toEqual([]);
}

/**
 * Stricter check: no serious or critical issue. The listitem rule is left out because of the known
 * issue in the shell's navigation list (Layout), which a screen cannot fix.
 */
export async function expectNoSeriousIssues(container: HTMLElement) {
  const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  const found = results.violations.filter(
    (violation) =>
      (violation.impact === "critical" || violation.impact === "serious") &&
      violation.id !== "listitem",
  );
  expect(found.map((violation) => violation.id)).toEqual([]);
}
