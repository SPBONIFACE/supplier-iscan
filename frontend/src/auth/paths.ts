import type { CurrentUser } from "../lib/api";

export const LOGIN_PATH = "/login";

export const isPublicPath = (pathname: string): boolean =>
  pathname === LOGIN_PATH || pathname.startsWith("/invitations/");

/** Login URL that brings the user back to `target` after signing in. */
export const loginUrl = (target: string): string =>
  target === "/" ? LOGIN_PATH : `${LOGIN_PATH}?next=${encodeURIComponent(target)}`;

/** Only same-site, in-app paths are accepted as a return target (no open redirect). */
export function safeNext(value: string | null): string | null {
  if (!value?.startsWith("/") || value.startsWith("//") || value.includes("\\")) return null;
  // Tabs, newlines and other control characters are never part of an in-app path.
  // biome-ignore lint/suspicious/noControlCharactersInRegex: rejecting them is the point
  if (/[\u0000-\u001f\u007f]/.test(value)) return null;
  return isPublicPath(value.split("?")[0] ?? value) ? null : value;
}

/** Members land in the workspace, administrators in the administrator area. */
export const homePath = (user: CurrentUser): string =>
  user.role === "admin" ? "/admin" : "/workspace";
