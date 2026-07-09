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
  CertificationRequest,
  CertificationResponse,
  DqIssue,
  ErrorEnvelope,
  LineageNode,
  LoginRequest,
  LoginResponse,
  MetricValue,
  ResolveRequest,
  ResolveResponse,
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
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const session = getSession();
  if (session) headers["Authorization"] = `Bearer ${session.token}`;

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
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
  return (await response.json()) as T;
}

// ---- endpoints (exactly the six paths in openapi.json) ----

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

export function listDqIssues(status?: string): Promise<DqIssue[]> {
  const qs = status ? `?${new URLSearchParams({ status })}` : "";
  return request<DqIssue[]>("GET", `/dq/issues${qs}`);
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
