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
  AttestationCreated,
  AttestationRecord,
  AttestationRequest,
  AttestationRevokeRequest,
  AttestationRevoked,
  Branding,
  CertificationCertificate,
  CertificationIntent,
  CertificationRequest,
  CertificationResponse,
  VerificationResult,
  CompareResponse,
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
  SafetyDeadlines,
  SafetyEventCreated,
  SafetyEventRecord,
  SafetyEventRequest,
  SafetyEventSuperseded,
  SafetySupersedeRequest,
  SamplingDrawCreated,
  SamplingDrawRecord,
  SamplingDrawRequest,
  SamplingEstimateRequest,
  SamplingEstimateResponse,
  SamplingMeasurementCreated,
  SamplingMeasurementRecord,
  SamplingMeasurementRequest,
  SamplingOptions,
  SamplingPlanCreated,
  SamplingPlanProgress,
  SamplingPlanRecord,
  SamplingPlanRequest,
  SandboxPreviewRequest,
  SandboxPreviewResponse,
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
  opts: { auth?: boolean; rawText?: boolean; blob?: boolean } = {},
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
  // blob: a binary download (CSV/XLSX exports) — the body plus the response
  // headers, so the caller can honor the server's attachment filename.
  if (opts.blob) {
    return {
      blob: await response.blob(),
      contentDisposition: response.headers.get("content-disposition"),
    } as T;
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
  /**
   * "ntd" | "ops" (handoff 0014): the server-side honesty-boundary filter.
   * The certify cockpit passes "ntd" so operations metrics — which the API
   * and the database refuse to certify — never even appear beside a
   * signature checkbox.
   */
  category?: string;
}

export function listMetricValues(
  filters: MetricValueFilters = {},
): Promise<MetricValue[]> {
  const params = new URLSearchParams();
  if (filters.metric) params.set("metric", filters.metric);
  if (filters.period_start) params.set("period_start", filters.period_start);
  if (filters.period_end) params.set("period_end", filters.period_end);
  if (filters.category) params.set("category", filters.category);
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

// ---- signature + attestations (handoff 0019) ----
//
// Typed against services/api routers/certify.py + attestations.py EXACTLY
// (reconciled 2026-07-15 against the backend's parallel build; final check
// against the regenerated openapi.json when it lands).

/**
 * GET /certifications/intent — the fixed statements the signing ceremony
 * renders: the ESIGN-style intent statement and the honest-scope
 * statement. SERVER-SERVED so screen and signed record carry the same
 * words; if this cannot be loaded, the ceremony refuses to arm (a
 * signature must never be given against words the server did not state).
 */
export function getCertificationIntent(): Promise<CertificationIntent> {
  return request<CertificationIntent>("GET", "/certifications/intent");
}

/**
 * GET /certifications/{id} — the certificate: the record, the raw signed
 * bytes, the parsed canonical document, and a LIVE verification result
 * the server computes on every read. Rendered verbatim by the UI.
 */
export function getCertification(
  certificationId: string,
): Promise<CertificationCertificate> {
  return request<CertificationCertificate>(
    "GET",
    `/certifications/${encodeURIComponent(certificationId)}`,
  );
}

/**
 * GET /certifications/{id}/verify — the server re-verifies the stored
 * canonical document against the stored signature (handoff 0019 design 6).
 * The UI shows the verdict verbatim, verified or FAILED — never softened.
 */
export function verifyCertification(
  certificationId: string,
): Promise<VerificationResult> {
  return request<VerificationResult>(
    "GET",
    `/certifications/${encodeURIComponent(certificationId)}/verify`,
  );
}

/** GET /attestations — every recorded statistician attestation, revoked
 *  ones included (append-only history; any signed-in role reads). */
export function listAttestations(): Promise<AttestationRecord[]> {
  return request<AttestationRecord[]>("GET", "/attestations");
}

/**
 * POST /attestations (certifying_official — enforced server-side;
 * audited). Records that a qualified statistician approved a factoring
 * method for a declared scope. The UI records the approval's existence
 * and pointer — never the approval document itself.
 */
export function createAttestation(
  body: AttestationRequest,
): Promise<AttestationCreated> {
  return request<AttestationCreated>("POST", "/attestations", body);
}

/**
 * POST /attestations/{id}/revoke (certifying_official; audited). Revokes
 * — never deletes: the row stays visible with its revocation trio, and
 * figures already factored under it keep their provenance permanently.
 */
export function revokeAttestation(
  attestationId: string,
  body: AttestationRevokeRequest,
): Promise<AttestationRevoked> {
  return request<AttestationRevoked>(
    "POST",
    `/attestations/${encodeURIComponent(attestationId)}/revoke`,
    body,
  );
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

// ---- safety & security (handoff 0010) ----

/**
 * POST /safety/events (data_steward+ — enforced server-side; audited). The
 * API runs the deterministic classifier synchronously and returns the
 * verdict with thresholds met and plain-language explanations. The UI
 * displays that verdict verbatim — it never classifies an event.
 */
export function createSafetyEvent(
  body: SafetyEventRequest,
): Promise<SafetyEventCreated> {
  return request<SafetyEventCreated>("POST", "/safety/events", body);
}

export interface SafetyEventFilters {
  classification?: string;
  /** YYYY-MM */
  month?: string;
  mode?: string;
}

export function listSafetyEvents(
  filters: SafetyEventFilters = {},
): Promise<SafetyEventRecord[]> {
  const params = new URLSearchParams();
  if (filters.classification) params.set("classification", filters.classification);
  if (filters.month) params.set("month", filters.month);
  if (filters.mode) params.set("mode", filters.mode);
  const qs = params.toString();
  return request<SafetyEventRecord[]>(
    "GET",
    `/safety/events${qs ? `?${qs}` : ""}`,
  );
}

/**
 * POST /safety/events/{id}/supersede (data_steward+; audited). Corrections
 * are APPEND-ONLY: the API records a NEW event (classified like any other)
 * and links the original to it via superseded_by — the original is never
 * edited or deleted. The body carries the corrected answers PLUS a required
 * reason (kept in the audit log).
 */
export function supersedeSafetyEvent(
  eventId: string,
  body: SafetySupersedeRequest,
): Promise<SafetyEventSuperseded> {
  return request<SafetyEventSuperseded>(
    "POST",
    `/safety/events/${encodeURIComponent(eventId)}/supersede`,
    body,
  );
}

/**
 * GET /safety/deadlines — due dates computed BY THE API: per open major
 * event an S&S-40 (occurred_at + 30 days, Exhibit 2), and per mode for the
 * given month (default: the current UTC month) an S&S-50 (due end of the
 * following month, Exhibit 3) INCLUDING zero-event rows.
 */
export function getSafetyDeadlines(month?: string): Promise<SafetyDeadlines> {
  const qs = month ? `?${new URLSearchParams({ month })}` : "";
  return request<SafetyDeadlines>("GET", `/safety/deadlines${qs}`);
}

// ---- sampling (handoff 0012) ----
//
// Typed against services/api routers/sampling.py exactly (the module was
// built in parallel against the same handoff). The measurement-supersede
// endpoint (POST /sampling/measurements/{id}/supersede) exists in the API
// but has no UI room yet — an honest v0 gap recorded in the handoff
// evidence, not a hidden one: the API's own 409 for a duplicate
// measurement names that endpoint and is surfaced verbatim.

/**
 * GET /sampling/options — the wizard's vocabulary (modes, Table 41.01
 * units per mode, efficiency options and which are creatable,
 * frequencies, day types) plus the calc's eligibility guidance and
 * retention note, all verbatim. Any signed-in role.
 */
export function getSamplingOptions(): Promise<SamplingOptions> {
  return request<SamplingOptions>("GET", "/sampling/options");
}

/**
 * POST /sampling/plans (data_steward+ — enforced server-side; audited).
 * The deterministic sampling_v0 selector supplies the required per-period
 * and annual sizes verbatim from Tables 43.01–43.07 with their citation.
 * The UI displays those sizes — it never computes one.
 */
export function createSamplingPlan(
  body: SamplingPlanRequest,
): Promise<SamplingPlanCreated> {
  return request<SamplingPlanCreated>("POST", "/sampling/plans", body);
}

/** GET /sampling/plans — every recorded plan, any signed-in role. */
export function listSamplingPlans(): Promise<SamplingPlanRecord[]> {
  return request<SamplingPlanRecord[]>("GET", "/sampling/plans");
}

/** GET /sampling/plans/{id}/draws — the plan's recorded period draws. */
export function listSamplingDraws(
  planId: string,
): Promise<SamplingDrawRecord[]> {
  return request<SamplingDrawRecord[]>(
    "GET",
    `/sampling/plans/${encodeURIComponent(planId)}/draws`,
  );
}

/**
 * POST /sampling/plans/{id}/draws (data_steward+; audited): one seeded,
 * WITHOUT-replacement random-selection act for one period (§63.03),
 * drawn by the versioned calc drawer. The UI never draws — it displays
 * the drawn list and the recorded seed.
 */
export function drawSamplingPeriod(
  planId: string,
  body: SamplingDrawRequest,
): Promise<SamplingDrawCreated> {
  return request<SamplingDrawCreated>(
    "POST",
    `/sampling/plans/${encodeURIComponent(planId)}/draws`,
    body,
  );
}

/** GET /sampling/plans/{id}/measurements — every recorded observation,
 *  superseded ones included (append-only history). */
export function listSamplingMeasurements(
  planId: string,
): Promise<SamplingMeasurementRecord[]> {
  return request<SamplingMeasurementRecord[]>(
    "GET",
    `/sampling/plans/${encodeURIComponent(planId)}/measurements`,
  );
}

/**
 * POST /sampling/plans/{id}/measurements (data_steward+; audited): one
 * ride-check observation for one drawn unit. observed_pmt stays a
 * decimal string end to end.
 */
export function recordSamplingMeasurement(
  planId: string,
  body: SamplingMeasurementRequest,
): Promise<SamplingMeasurementCreated> {
  return request<SamplingMeasurementCreated>(
    "POST",
    `/sampling/plans/${encodeURIComponent(planId)}/measurements`,
    body,
  );
}

/**
 * GET /sampling/plans/{id}/progress — measured vs required, per draw and
 * overall, with the unmeasured-unit worksheet, all computed BY THE API.
 */
export function getSamplingProgress(
  planId: string,
): Promise<SamplingPlanProgress> {
  return request<SamplingPlanProgress>(
    "GET",
    `/sampling/plans/${encodeURIComponent(planId)}/progress`,
  );
}

/**
 * POST /sampling/plans/{id}/estimate (report_preparer+ — enforced
 * server-side; audited): the §83 APTL estimate — sample APTL as a RATIO
 * OF TOTALS (§83.05) expanded by the supplied 100% UPT count (§83.01).
 * Computed by sampling_v0, never by this UI; undersampled and
 * Base-option plans are refused by the API and the refusal is surfaced
 * verbatim. The result is a SAMPLED ESTIMATE — never persisted to
 * computed.metric_values.
 */
export function estimateSamplingPmt(
  planId: string,
  body: SamplingEstimateRequest,
): Promise<SamplingEstimateResponse> {
  return request<SamplingEstimateResponse>(
    "POST",
    `/sampling/plans/${encodeURIComponent(planId)}/estimate`,
    body,
  );
}

// ---- comparison + sandbox (handoff 0017) ----
//
// Both endpoints were built in parallel against the same handoff and are
// typed against the REGENERATED openapi.json (reconciled 2026-07-14; the
// original parallel-build mocks guessed a different comparand token order
// and a flat sandbox body — both corrected here against the export).

/**
 * One comparand token, exactly as GET /metrics/compare parses it:
 * '<period_start>..<period_end>' (ISO dates, half-open) optionally followed
 * by '@<calc_name>:<calc_version>' to pin one calculation version. The
 * first comparand in the request is the baseline.
 */
export function comparandToken(
  periodStart: string,
  periodEnd: string,
  calcName?: string,
  calcVersion?: string,
): string {
  const period = `${periodStart}..${periodEnd}`;
  return calcName && calcVersion
    ? `${period}@${calcName}:${calcVersion}`
    : period;
}

export interface CompareQuery {
  metric: string;
  /** 2–4 comparand tokens; the FIRST is the baseline. */
  comparands: string[];
  /** Optional scope subset; omitted = every scope with a figure. */
  scopes?: string[];
}

/**
 * GET /metrics/compare (handoff 0017, design point 1): the same reader as
 * GET /metrics/values COMPOSED per comparand — values verbatim, deltas
 * computed server-side in exact Decimal arithmetic and served as signed
 * strings, direction metadata from the calc library's metric registry.
 * This UI renders the response; it never subtracts two figures.
 */
export function getMetricsCompare(query: CompareQuery): Promise<CompareResponse> {
  const params = new URLSearchParams();
  params.set("metric", query.metric);
  for (const token of query.comparands) params.append("comparand", token);
  for (const scope of query.scopes ?? []) params.append("scope", scope);
  return request<CompareResponse>("GET", `/metrics/compare?${params}`);
}

/**
 * POST /sandbox/preview (handoff 0017, design point 6): a what-if PREVIEW
 * recomputation for one period under proposed knob values, vs the current
 * audited settings, over the SAME canonical inputs. Changes nothing: the
 * calc preview entry points perform no writes, `persisted` is a constant
 * false, and previews are ephemeral — they exist only in the response.
 * Applying a knob stays in the separate audited settings flow (the
 * response's settings_flow_note names it verbatim).
 */
export function runSandboxPreview(
  body: SandboxPreviewRequest,
): Promise<SandboxPreviewResponse> {
  return request<SandboxPreviewResponse>("POST", "/sandbox/preview", body);
}

// ---- server exports (handoff 0017, design point 5) ----
//
// CSV/XLSX downloads served by the API. Both formats come from ONE server-
// side row assembly (services/api headway_api/exports.py): every XLSX data
// cell is a TEXT cell holding the byte-identical string the CSV holds, so a
// figure survives exactly as served. The saved file is the response body
// byte for byte — nothing here parses, reorders, or re-encodes it.

export type ExportFormat = "csv" | "xlsx";

/** One fetched export: the response bytes plus the name to save them as. */
export interface ExportDownload {
  blob: Blob;
  filename: string;
}

/** What request() hands back for a blob download, pre-filename. */
interface BlobResult {
  blob: Blob;
  contentDisposition: string | null;
}

/**
 * The server names every export via Content-Disposition (surface + period
 * in the stem); that name wins. The fallback mirrors the server's stem
 * convention for the rare response without the header.
 */
function attachmentFilename(
  contentDisposition: string | null,
  fallback: string,
): string {
  const match = /filename="([^"]+)"/.exec(contentDisposition ?? "");
  return match ? match[1] : fallback;
}

async function requestExport(
  path: string,
  fallbackFilename: string,
): Promise<ExportDownload> {
  const result = await request<BlobResult>("GET", path, undefined, {
    blob: true,
  });
  return {
    blob: result.blob,
    filename: attachmentFilename(result.contentDisposition, fallbackFilename),
  };
}

/**
 * GET /metrics/values/export — the SAME rows GET /metrics/values serves
 * (same optional filters), as a download. Columns are the retired
 * client-side CSV's plus scope, category (the migration-0024 honesty
 * boundary) and metric_value_id (the provenance path); the preview
 * disclaimer — and a simulated-data warning when any row is simulated —
 * leads the CSV and forms the XLSX's first sheet.
 */
export function downloadMetricValuesExport(
  format: ExportFormat,
  filters: Pick<MetricValueFilters, "period_start" | "period_end"> = {},
): Promise<ExportDownload> {
  const params = new URLSearchParams();
  if (filters.period_start) params.set("period_start", filters.period_start);
  if (filters.period_end) params.set("period_end", filters.period_end);
  params.set("format", format);
  const stem = [
    "headway-metric-values",
    ...(filters.period_start ? [filters.period_start] : []),
    ...(filters.period_end ? [filters.period_end] : []),
  ].join("-");
  return requestExport(
    `/metrics/values/export?${params}`,
    `${stem}.${format}`,
  );
}

/**
 * GET /reports/mr20/export?month= — the MR-20 preview package as a grid:
 * one row per (scope, metric) cell, values verbatim from the package; its
 * NOT-REPORTABLE banner and every caveat lead the file.
 */
export function downloadMr20Export(
  month: string,
  format: ExportFormat,
): Promise<ExportDownload> {
  const params = new URLSearchParams({ month, format });
  return requestExport(
    `/reports/mr20/export?${params}`,
    `headway-mr20-${month}-preview.${format}`,
  );
}

/**
 * GET /reports/ss50/export?month= — the S&S-50 non-major monthly summary
 * package: one row per (mode, type-of-service) cell INCLUDING explicit
 * zero-event rows; banner, citations, caveats and the excluded-event
 * accounting lead the file.
 */
export function downloadSs50Export(
  month: string,
  format: ExportFormat,
): Promise<ExportDownload> {
  const params = new URLSearchParams({ month, format });
  return requestExport(
    `/reports/ss50/export?${params}`,
    `headway-ss50-${month}-preview.${format}`,
  );
}

/**
 * GET /sampling/plans/{id}/worksheet — the plan's measurement worksheet:
 * one row per selected unit per draw with its measured state; the plan's
 * requirement, the undersampled/estimate-ready state and the retention
 * note lead the file.
 */
export function downloadSamplingWorksheet(
  planId: string,
  format: ExportFormat,
): Promise<ExportDownload> {
  const params = new URLSearchParams({ format });
  return requestExport(
    `/sampling/plans/${encodeURIComponent(planId)}/worksheet?${params}`,
    `headway-sampling-worksheet-${planId}.${format}`,
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
