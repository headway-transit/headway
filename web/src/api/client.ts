/**
 * Thin typed client over the Headway API (services/api/openapi.json).
 *
 * - Attaches the bearer token from the in-memory session.
 * - Maps 401 on any authenticated call to a login redirect (session cleared,
 *   registered unauthorized handler invoked).
 * - Surfaces API error messages VERBATIM: the API writes plain-language
 *   errors by design, so the UI never rewrites or softens them.
 * - Reported figures stay strings end to end (see MetricValue.value).
 */

import { clearSession, getSession } from "../auth/session";
import type {
  Branding,
  CertificationRequest,
  CertificationResponse,
  DqIssue,
  ErrorEnvelope,
  LineageNode,
  LoginRequest,
  LoginResponse,
  LogoUploadResponse,
  MetricValue,
  Mr20Package,
  PublicMetricValue,
  ResolveRequest,
  ResolveResponse,
  Setting,
  UpdateSettingResponse,
} from "./types";

/** Base URL for the API; empty string = same origin (dev proxy / co-hosting). */
const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** 0 = network failure (no HTTP status). */
export const NETWORK_ERROR_STATUS = 0;

const NETWORK_ERROR_MESSAGE =
  "Headway could not reach the server. Check your connection and try again.";

const UNREADABLE_ERROR_MESSAGE =
  "The server reported an error but the message could not be read.";

let unauthorizedHandler: (() => void) | null = null;

/**
 * Register what "redirect to login" means (set once by the app shell, which
 * owns navigation). Called after the session is cleared on any 401.
 */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

async function extractErrorMessage(response: Response): Promise<string> {
  let body: ErrorEnvelope;
  try {
    body = (await response.json()) as ErrorEnvelope;
  } catch {
    return UNREADABLE_ERROR_MESSAGE;
  }
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) {
    // 422 validation errors: surface every message, verbatim.
    return body.detail.map((item) => item.msg).join(" ");
  }
  return UNREADABLE_ERROR_MESSAGE;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts: { auth?: boolean; rawText?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  // FormData (multipart upload) sets its own Content-Type with the boundary;
  // JSON bodies get the explicit header.
  const isFormData =
    typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isFormData) {
    headers["Content-Type"] = "application/json";
  }
  const session = getSession();
  // auth: false = a deliberately unauthenticated endpoint (/public/*): the
  // bearer token is never attached, even when a session exists.
  if (session && opts.auth !== false) {
    headers["Authorization"] = `Bearer ${session.token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body:
        body === undefined
          ? undefined
          : isFormData
            ? (body as FormData)
            : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(NETWORK_ERROR_STATUS, NETWORK_ERROR_MESSAGE);
  }

  if (response.status === 401 && path !== "/auth/login") {
    // Session invalid or expired: clear it and send the user to sign in.
    const message = await extractErrorMessage(response);
    clearSession();
    unauthorizedHandler?.();
    throw new ApiError(401, message);
  }

  if (!response.ok) {
    throw new ApiError(response.status, await extractErrorMessage(response));
  }
  // rawText: the caller needs the response BYTES verbatim (e.g. the MR-20
  // "download package" button must save exactly what was fetched, never a
  // re-serialization that could reorder keys or reformat numbers).
  if (opts.rawText) {
    return (await response.text()) as T;
  }
  return (await response.json()) as T;
}

// ---- endpoints (exactly the paths this UI uses from openapi.json) ----

export function login(credentials: LoginRequest): Promise<LoginResponse> {
  return request<LoginResponse>("POST", "/auth/login", credentials);
}

export interface MetricValueFilters {
  metric?: string;
  period_start?: string;
  period_end?: string;
}

export function listMetricValues(
  filters: MetricValueFilters = {},
): Promise<MetricValue[]> {
  const params = new URLSearchParams();
  if (filters.metric) params.set("metric", filters.metric);
  if (filters.period_start) params.set("period_start", filters.period_start);
  if (filters.period_end) params.set("period_end", filters.period_end);
  const qs = params.toString();
  return request<MetricValue[]>(
    "GET",
    `/metrics/values${qs ? `?${qs}` : ""}`,
  );
}

export function getLineage(metricValueId: string): Promise<LineageNode> {
  return request<LineageNode>(
    "GET",
    `/metrics/values/${encodeURIComponent(metricValueId)}/lineage`,
  );
}

export function certify(
  body: CertificationRequest,
): Promise<CertificationResponse> {
  return request<CertificationResponse>("POST", "/certifications", body);
}

/** The one deliberately unauthenticated path (handoff 0006, design point 8). */
const PUBLIC_CERTIFIED_PATH = "/public/metrics/certified";

/**
 * The raw machine-readable URL of the certified open-data feed, for the
 * "machine-readable version" link on /public.
 */
export function publicCertifiedValuesUrl(): string {
  return `${BASE_URL}${PUBLIC_CERTIFIED_PATH}`;
}

/**
 * GET /public/metrics/certified — UNAUTHENTICATED by design: only figures a
 * certifying official has already attested to, values as strings verbatim,
 * detail verbatim (simulated flags included), no PII. No token is sent.
 */
export function listPublicCertifiedValues(): Promise<PublicMetricValue[]> {
  return request<PublicMetricValue[]>("GET", PUBLIC_CERTIFIED_PATH, undefined, {
    auth: false,
  });
}

export function listDqIssues(status?: string): Promise<DqIssue[]> {
  const qs = status ? `?${new URLSearchParams({ status })}` : "";
  return request<DqIssue[]>("GET", `/dq/issues${qs}`);
}

/**
 * GET /reports/mr20?month=YYYY-MM. Returns BOTH the parsed package (for
 * rendering) and the raw response text: the "Download package (JSON)" button
 * saves the raw text so the file is byte-identical to what the API served —
 * JSON.stringify(pkg) could reorder keys or reformat and is never used.
 */
export interface Mr20Fetch {
  pkg: Mr20Package;
  raw: string;
}

export async function getMr20Report(month: string): Promise<Mr20Fetch> {
  const raw = await request<string>(
    "GET",
    `/reports/mr20?${new URLSearchParams({ month })}`,
    undefined,
    { rawText: true },
  );
  return { pkg: JSON.parse(raw) as Mr20Package, raw };
}

export function resolveDqIssue(
  issueId: string,
  body: ResolveRequest,
): Promise<ResolveResponse> {
  return request<ResolveResponse>(
    "POST",
    `/dq/issues/${encodeURIComponent(issueId)}/resolve`,
    body,
  );
}

// ---- branding + settings (handoff 0008, pillar C) ----

/**
 * GET /branding — UNAUTHENTICATED by design: the shell brands itself before
 * sign-in. Colors served here already passed the server-side WCAG AA
 * contrast guardrail at write time.
 */
export function getBranding(): Promise<Branding> {
  return request<Branding>("GET", "/branding", undefined, { auth: false });
}

/**
 * The URL of GET /branding/logo (unauthenticated, cache-headed) for use as
 * an <img src>. The shell only renders it when GET /branding says a logo
 * exists.
 */
export function brandingLogoUrl(): string {
  return `${BASE_URL}/branding/logo`;
}

/** GET /settings — any signed-in role may read agency policy settings. */
export function listSettings(): Promise<Setting[]> {
  return request<Setting[]>("GET", "/settings");
}

/**
 * PUT /settings/{key} (certifying official only — enforced server-side).
 * Brand colors are contrast-checked BY THE SERVER; a failing color comes
 * back as a plain-language 422 that the UI surfaces verbatim.
 */
export function updateSetting(
  settingKey: string,
  value: string,
): Promise<UpdateSettingResponse> {
  return request<UpdateSettingResponse>(
    "PUT",
    `/settings/${encodeURIComponent(settingKey)}`,
    { value },
  );
}

/**
 * POST /branding/logo (certifying official only — enforced server-side).
 * Multipart, field name "file"; SVG or PNG, at most 512 KiB — oversize or
 * wrong-type files come back as plain-language 413/415 errors, surfaced
 * verbatim.
 */
export function uploadLogo(file: File): Promise<LogoUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  return request<LogoUploadResponse>("POST", "/branding/logo", form);
}
