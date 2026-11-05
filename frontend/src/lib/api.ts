// The single API client. Every backend call of the frontend goes through this module; no other file
// may call fetch, XMLHttpRequest or an HTTP library (enforced by Biome and by src/lib/no-direct-http.test.ts).
// Request and response types are generated from openapi.yaml (`pnpm api:types`, src/lib/api-schema.d.ts).
import createClient from "openapi-fetch";
import type { components, paths } from "./api-schema";

export type CurrentUser = components["schemas"]["CurrentUser"];
export type InvitationCheck = components["schemas"]["InvitationCheck"];
export type Language = components["schemas"]["Language"];
export type IdentitySession = components["schemas"]["IdentitySession"];
export type IdentityTurn = components["schemas"]["IdentityTurn"];
export type IdentityCandidate = components["schemas"]["IdentityCandidate"];
export type IdentityConfirmed = components["schemas"]["IdentityConfirmed"];
export type IdentitySessionCreate = components["schemas"]["IdentitySessionCreate"];
export type MemberOrganisation = components["schemas"]["MemberOrganisation"];
export type Run = components["schemas"]["Run"];
export type RunStatus = components["schemas"]["RunStatus"];
export type RunStage = components["schemas"]["RunStage"];
export type RunDependency = components["schemas"]["RunDependency"];
export type RunFailure = components["schemas"]["RunFailure"];
export type Fact = components["schemas"]["Fact"];
export type FactReview = components["schemas"]["FactReview"];
export type Assessment = components["schemas"]["Assessment"];
export type AssessmentStatement = components["schemas"]["AssessmentStatement"];
export type StatementReview = components["schemas"]["StatementReview"];
export type FinancialGuidance = components["schemas"]["FinancialGuidance"];
export type BuyerInputs = components["schemas"]["BuyerInputs"];
export type BuyerInput = components["schemas"]["BuyerInput"];
export type BuyerContext = components["schemas"]["BuyerContext"];
export type BuyerContextUpdate = components["schemas"]["BuyerContextUpdate"];
export type StrategicIntent = components["schemas"]["StrategicIntent"];
export type Criteria = components["schemas"]["Criteria"];
export type CriteriaUpdate = components["schemas"]["CriteriaUpdate"];
export type BuyerInputUpdate = components["schemas"]["BuyerInputUpdate"];
export type DraftingPart = components["schemas"]["DraftingAccepted"]["part"];
export type ProfileField = components["schemas"]["ProfileField"];
export type ProfileDefinition = components["schemas"]["ProfileDefinition"];
export type RunRefusalReason = NonNullable<MemberOrganisation["run_refusal_reason"]>;
export type FieldError = components["schemas"]["ValidationError"]["errors"][number];

/** Why a call failed, in terms the screens act on. */
export type ApiFailure = {
  ok: false;
  kind: "unauthorized" | "not_found" | "conflict" | "validation" | "refused" | "unavailable";
  status: number;
  errors: FieldError[];
  /** Why a run start was refused (403 on POST /runs). */
  reason?: RunRefusalReason;
  /** The server's plain message on a 409 (matched only for the one case the screens tell apart). */
  detail?: string;
  /** The value stored now, on a 409 about an outdated version. The screen narrows its type. */
  current?: unknown;
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
            : status === 403
              ? "refused"
              : "unavailable";
  return { ok: false, kind, status, errors };
};

type Raw<T> = { data?: T; error?: unknown; response: Response };

function settle<T>(raw: Raw<T>): ApiResult<T> {
  if (raw.response.ok && raw.data !== undefined) return { ok: true, data: raw.data };
  const body = raw.error as
    | { errors?: FieldError[]; reason?: RunRefusalReason; detail?: unknown; current?: unknown }
    | undefined;
  const result = failure(raw.response.status, Array.isArray(body?.errors) ? body.errors : []);
  if (result.kind === "refused") return { ...result, reason: body?.reason };
  if (result.kind === "conflict") {
    return {
      ...result,
      detail: typeof body?.detail === "string" ? body.detail : undefined,
      current: body?.current,
    };
  }
  return result;
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

  getOrganisation: () => call(() => client.GET("/organisation")),

  listRuns: () => call(() => client.GET("/runs")),

  checkInvitation: (token: string) =>
    call(() => client.GET("/invitations/{token}", { params: { path: { token } } })),

  acceptInvitation: (token: string, password: string) =>
    call(() =>
      client.POST("/invitations/{token}/accept", {
        params: { path: { token } },
        body: { password },
      }),
    ),

  getDisclosure: (language: Language) =>
    call(() => client.GET("/identity/disclosure", { params: { query: { language } } })),

  createIdentitySession: (body: IdentitySessionCreate) =>
    call(() => client.POST("/identity-sessions", { body })),

  getIdentitySession: (id: string) =>
    call(() => client.GET("/identity-sessions/{id}", { params: { path: { id } } })),

  sendIdentityMessage: (id: string, text: string) =>
    call(() =>
      client.POST("/identity-sessions/{id}/messages", {
        params: { path: { id } },
        body: { text },
      }),
    ),

  listIdentityCandidates: (id: string) =>
    call(() => client.GET("/identity-sessions/{id}/candidates", { params: { path: { id } } })),

  submitIdentityWebsite: (id: string, website: string) =>
    call(() =>
      client.POST("/identity-sessions/{id}/website", {
        params: { path: { id } },
        body: { website },
      }),
    ),

  confirmIdentity: (id: string, candidateId: string) =>
    call(() =>
      client.POST("/identity-sessions/{id}/confirm", {
        params: { path: { id } },
        body: { candidate_id: candidateId },
      }),
    ),

  getRun: (id: string) => call(() => client.GET("/runs/{id}", { params: { path: { id } } })),

  listRunSources: (id: string) =>
    call(() => client.GET("/runs/{id}/sources", { params: { path: { id } } })),

  listRunFailures: (id: string) =>
    call(() => client.GET("/runs/{id}/failures", { params: { path: { id } } })),

  listRunFacts: (id: string) =>
    call(() => client.GET("/runs/{id}/facts", { params: { path: { id } } })),

  /** The supplier card as a PDF, in the UI language, with the file name the server proposes. */
  async downloadRunPdf(
    id: string,
    lang: Language,
  ): Promise<ApiResult<{ blob: Blob; filename: string }>> {
    try {
      const raw = await client.GET("/runs/{id}/pdf", {
        params: { path: { id }, query: { lang } },
        parseAs: "blob",
      });
      if (raw.response.ok && raw.data instanceof Blob) {
        const named = /filename="([A-Za-z0-9._-]+)"/.exec(
          raw.response.headers.get("Content-Disposition") ?? "",
        );
        return { ok: true, data: { blob: raw.data, filename: named?.[1] ?? "supplier-card.pdf" } };
      }
      return settle({ error: raw.error, response: raw.response });
    } catch {
      return failure(0);
    }
  },

  reviewFact: (id: string, body: FactReview) =>
    call(() => client.PATCH("/facts/{id}", { params: { path: { id } }, body })),

  reviewAssessmentStatement: (id: string, body: StatementReview) =>
    call(() => client.PATCH("/assessment-statements/{id}", { params: { path: { id } }, body })),

  getRunAssessment: (id: string) =>
    call(() => client.GET("/runs/{id}/assessment", { params: { path: { id } } })),

  getRunBuyerInputs: (id: string) =>
    call(() => client.GET("/runs/{id}/buyer-inputs", { params: { path: { id } } })),

  putRunCriteria: (id: string, body: CriteriaUpdate) =>
    call(() => client.PUT("/runs/{id}/criteria", { params: { path: { id } }, body })),

  putRunBuyerContext: (id: string, body: BuyerContextUpdate) =>
    call(() => client.PUT("/runs/{id}/buyer-context", { params: { path: { id } }, body })),

  putRunBuyerInput: (id: string, field: string, body: BuyerInputUpdate) =>
    call(() =>
      client.PUT("/runs/{id}/buyer-inputs/{field}", { params: { path: { id, field } }, body }),
    ),

  draftRunFit: (id: string) =>
    call(() => client.POST("/runs/{id}/fit", { params: { path: { id } } })),

  draftRunRecommendations: (id: string) =>
    call(() => client.POST("/runs/{id}/recommendations", { params: { path: { id } } })),

  stopRun: (id: string) => call(() => client.POST("/runs/{id}/stop", { params: { path: { id } } })),

  resumeRun: (id: string) =>
    call(() => client.POST("/runs/{id}/resume", { params: { path: { id } } })),

  getProfileDefinition: (language: Language) =>
    call(() => client.GET("/profile-definition", { params: { query: { language } } })),

  startRun: (identityId: string) =>
    call(() => client.POST("/runs", { body: { identity_id: identityId } })),
};
