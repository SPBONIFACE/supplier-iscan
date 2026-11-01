// The single API client. Every backend call of the frontend goes through this module; no other file
// may call fetch, XMLHttpRequest or an HTTP library (enforced by Biome and by src/lib/no-direct-http.test.ts).
// Request and response types are generated from openapi.yaml (`pnpm api:types`, src/lib/api-schema.d.ts).
import createClient from "openapi-fetch";
import type { components, paths } from "./api-schema";

export type CurrentUser = components["schemas"]["CurrentUser"];
export type InvitationCheck = components["schemas"]["InvitationCheck"];
export type FieldError = components["schemas"]["ValidationError"]["errors"][number];

/** Why a call failed, in terms the screens act on. */
export type ApiFailure = {
  ok: false;
  kind: "unauthorized" | "not_found" | "conflict" | "validation" | "unavailable";
  status: number;
  errors: FieldError[];
};
export type ApiResult<T> = { ok: true; data: T } | ApiFailure;

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// `fetch` is resolved at call time, so tests can replace it.
const client = createClient<paths>({
  baseUrl,
  credentials: "include",
  fetch: (request) => globalThis.fetch(request),
});

type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler | null = null;

/** Registers what happens on a 401 from a protected call (the app sends the user to the login screen). */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler;
}

// A 401 from the login call is its answer (wrong credentials), not an expired session.
const PUBLIC_PATHS = ["/auth/login"];

client.use({
  onResponse({ response, schemaPath }) {
    if (response.status === 401 && !PUBLIC_PATHS.includes(schemaPath)) {
      onUnauthorized?.();
    }
    return undefined;
  },
});

const failure = (status: number, errors: FieldError[] = []): ApiFailure => {
  const kind =
    status === 401
      ? "unauthorized"
      : status === 404
        ? "not_found"
        : status === 409
          ? "conflict"
          : status === 422
            ? "validation"
            : "unavailable";
  return { ok: false, kind, status, errors };
};

type Raw<T> = { data?: T; error?: unknown; response: Response };

function settle<T>(raw: Raw<T>): ApiResult<T> {
  if (raw.response.ok && raw.data !== undefined) return { ok: true, data: raw.data };
  const body = raw.error as { errors?: FieldError[] } | undefined;
  return failure(raw.response.status, Array.isArray(body?.errors) ? body.errors : []);
}

// A network error (API unreachable) is reported like a 503: the screens show the same plain message.
async function call<T>(run: () => Promise<Raw<T>>): Promise<ApiResult<T>> {
  try {
    return settle(await run());
  } catch {
    return failure(0);
  }
}

export const api = {
  login: (email: string, password: string) =>
    call(() => client.POST("/auth/login", { body: { email, password } })),

  async logout(): Promise<ApiResult<null>> {
    try {
      const { response } = await client.POST("/auth/logout");
      return response.ok ? { ok: true, data: null } : failure(response.status);
    } catch {
      return failure(0);
    }
  },

  getCurrentUser: () => call(() => client.GET("/auth/me")),

  checkInvitation: (token: string) =>
    call(() => client.GET("/invitations/{token}", { params: { path: { token } } })),

  acceptInvitation: (token: string, password: string) =>
    call(() =>
      client.POST("/invitations/{token}/accept", {
        params: { path: { token } },
        body: { password },
      }),
    ),
};
