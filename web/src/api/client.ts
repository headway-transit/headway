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
  ActiveChangeResponse,
  AttestRequest,
  AttestResponse,
  AttestationCreated,
  AttestationRecord,
  AttestationRequest,
  AttestationRevokeRequest,
  AttestationRevoked,
  BoardingReview,
  BoardingReviewCounts,
  BoardingReviewPage,
  Branding,
  CalcRunCreated,
  CalcRunRecord,
  CalcRunRequest,
  ChangeRoleResponse,
  CreateUserRequest,
  CreateUserResponse,
  CertificationCertificate,
  CertificationIntent,
  CertificationRecord,
  CertificationRequest,
  CertificationResponse,
  VerificationResult,
  CompareResponse,
  ClassifyBoardingRequest,
  ClassifyBoardingResponse,
  DqIssue,
  DqIssueCounts,
  DqIssuePage,
  ErrorEnvelope,
  HistoryResponse,
  LineageNode,
  LoginRequest,
  LoginResponse,
  LogoDeleteResponse,
  LogoUploadResponse,
  MetricValue,
  Mr20Package,
  OpsVehiclesLatest,
  PublicMetricValue,
  RawRecordLabel,
  RawRecordPreview,
  RawRecordVerdict,
  ResetPasswordResponse,
  RoutesCollection,
  ResolveRequest,
  ResolveResponse,
  SafetyDeadlines,
  SafetyEventCounts,
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
  SourcesStatusResponse,
  StopsCollection,
  UpdateSettingResponse,
  UserRecord,
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

/**
 * The unauthenticated sign-in endpoints. A 401 from either means "that
 * sign-in attempt failed", never "your session expired", so neither one
 * clears a session or triggers the login redirect: doing so would take the
 * sign-in screen out from under its own error message before it could be
 * read. The screen that made the call owns the outcome.
 */
const SIGN_IN_PATHS = new Set(["/auth/login", "/auth/oidc/callback"]);

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

  if (response.status === 401 && !SIGN_IN_PATHS.has(path)) {
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
 * GET /certifications — every certification record, oldest first (any
 * signed-in role). Legacy (pre-signature) records come back with
 * signed=false and null signer fields — rendered honestly, never
 * backfilled. The index room (/certifications) lists exactly this.
 */
export function listCertifications(): Promise<CertificationRecord[]> {
  return request<CertificationRecord[]>("GET", "/certifications");
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

/**
 * GET /public/certifications/{id}/verify — the PUBLIC tamper-evidence
 * check (handoff 0019, designs 6–7): the server re-verifies the stored
 * certificate bytes against the stored Ed25519 signature and returns the
 * verdict. UNAUTHENTICATED by design (no token is ever sent), rate-limited
 * per client IP, and the payload never carries the certifier's identity.
 * The UI renders the verdict verbatim, verified or FAILED — never softened.
 */
export function publicVerifyCertification(
  certificationId: string,
): Promise<VerificationResult> {
  return request<VerificationResult>(
    "GET",
    `/public/certifications/${encodeURIComponent(certificationId)}/verify`,
    undefined,
    { auth: false },
  );
}

/**
 * GET /dq/issues (handoff 0030): ONE BOUNDED PAGE of the data-quality
 * queue.
 *
 * Until this wave this call downloaded the whole queue — measured live at
 * 98,497 issues, 850 MB, 17 s, and a frozen browser tab. The server now
 * caps a page at 200 rows (50 by default) and hands back a cursor for the
 * next one; the response also carries the whole-queue `total` under the
 * same filters, so nothing on screen has to mistake the loaded rows for
 * the queue.
 *
 * `status` and `severity` filter on the SERVER. That matters: with one
 * page loaded, filtering in the browser would filter the page, and a card
 * reading "8,824 blocking" above two visible rows is exactly the quiet
 * lie this project refuses.
 */
export function listDqIssues(params?: {
  status?: string;
  severity?: string;
  limit?: number;
  cursor?: string;
}): Promise<DqIssuePage> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.severity) query.set("severity", params.severity);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.cursor) query.set("cursor", params.cursor);
  const qs = query.toString();
  return request<DqIssuePage>("GET", `/dq/issues${qs ? `?${qs}` : ""}`);
}

/**
 * GET /dq/issues/{id} (handoff 0026): one finding directly — the deep-link
 * target a calculation refusal points at (/dq?issue=<id>). Fetched on its
 * own so the linked finding renders immediately, independent of the queue.
 *
 * Since handoff 0030 this is also the ONLY place `source_record_ids` is
 * served: the complete, untruncated provenance array for the one finding
 * being worked. The queue rows link here, so the path from a finding back
 * to its raw records is one request rather than an 850 MB download.
 */
export function getDqIssue(issueId: string): Promise<DqIssue> {
  return request<DqIssue>(
    "GET",
    `/dq/issues/${encodeURIComponent(issueId)}`,
  );
}

/**
 * GET /dq/issues/counts (built in handoff 0017, consumed by /today per
 * handoff 0021): server-side counts over EXACTLY the rows GET /dq/issues
 * serves under the same status filter — a briefing card total can never
 * disagree with the queue behind its door, and /today never downloads the
 * whole issue list just to count it.
 */
export function getDqIssueCounts(status?: string): Promise<DqIssueCounts> {
  const qs = status ? `?${new URLSearchParams({ status })}` : "";
  return request<DqIssueCounts>("GET", `/dq/issues/counts${qs}`);
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

/**
 * POST /dq/issues/{id}/attest (data_steward+ — the same rule as every
 * resolution, enforced server-side; audited). Closes ONE p. 146 refusal
 * issue under a RECORDED statistician attestation, to the explicit
 * 'attested' state (migration 0029). The server refuses any other issue
 * type loudly (no other gap has a statistician cure), refuses revoked
 * attestations, and builds the resolution text itself from the record.
 */
export function attestDqIssue(
  issueId: string,
  body: AttestRequest,
): Promise<AttestResponse> {
  return request<AttestResponse>(
    "POST",
    `/dq/issues/${encodeURIComponent(issueId)}/attest`,
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
 * GET /safety/events/counts (built in handoff 0017, consumed by /today per
 * handoff 0021): server-side counts over EXACTLY the rows GET
 * /safety/events serves under the same filters — the month card's tallies
 * can never disagree with the events list behind its door.
 */
export function getSafetyEventCounts(
  filters: Pick<SafetyEventFilters, "month" | "mode"> = {},
): Promise<SafetyEventCounts> {
  const params = new URLSearchParams();
  if (filters.month) params.set("month", filters.month);
  if (filters.mode) params.set("mode", filters.mode);
  const qs = params.toString();
  return request<SafetyEventCounts>(
    "GET",
    `/safety/events/counts${qs ? `?${qs}` : ""}`,
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
 * GET /reports/agency-workbook?month= — the monthly agency workbook
 * (handoff 0020, design point 3): the familiar monthly metrics workbook
 * assembled by the API — ridership-by-mode and operations sheets, a
 * provenance id per data cell, the "Read first" banner sheet leading, CSV
 * via the same grid. CONTRACT-AHEAD NOTE (2026-07-15): typed against the
 * handoff-0020 contract while the backend endpoint is still in flight; if
 * the server does not serve the route yet, its refusal renders verbatim
 * at the control. Reconcile against the regenerated openapi.json when it
 * lands.
 */
export function downloadAgencyWorkbook(
  month: string,
  format: ExportFormat,
): Promise<ExportDownload> {
  const params = new URLSearchParams({ month, format });
  return requestExport(
    `/reports/agency-workbook?${params}`,
    `headway-agency-workbook-${month}.${format}`,
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

// ---- the living map + audience lenses (handoffs 0023/0024) ----

/**
 * GET /ops/vehicles/latest — latest position per vehicle within a staleness
 * window (any signed-in role). OPS category: never certified, never a gate
 * on certification; the map badges the surface and renders the envelope's
 * honesty fields (note, newest_position_at) verbatim. Poll guidance from
 * the endpoint's own docstring: the upstream GTFS-RT connector polls every
 * ~30 s, so 15–30 s is the recommended map poll interval.
 */
export function getLatestVehicles(
  maxAgeSeconds?: number,
): Promise<OpsVehiclesLatest> {
  const qs =
    maxAgeSeconds !== undefined
      ? `?${new URLSearchParams({ max_age_seconds: String(maxAgeSeconds) })}`
      : "";
  return request<OpsVehiclesLatest>("GET", `/ops/vehicles/latest${qs}`);
}

/**
 * GET /geometry/stops — GeoJSON FeatureCollection of every canonical stop
 * with coordinates (any signed-in role). Stops without coordinates are
 * COUNTED in the envelope, never invented onto the map.
 */
export function getStopsGeojson(): Promise<StopsCollection> {
  return request<StopsCollection>("GET", "/geometry/stops");
}

/**
 * GET /geometry/routes — the honest schematic (any signed-in role):
 * straight lines through each route's most common trip pattern, labeled
 * `schematic_stop_sequence` by the server. The map legend renders the
 * server's geometry_note VERBATIM — these lines show structure, not
 * streets, and must never be presented as the path vehicles drive.
 */
export function getRoutesGeojson(): Promise<RoutesCollection> {
  return request<RoutesCollection>("GET", "/geometry/routes");
}

export interface HistoryQuery {
  metric?: string;
  /** Convenience for scope "mode:<mode>"; mutually exclusive with scope. */
  mode?: string;
  scope?: string;
  calc_version?: string;
  /** ISO date: only figures whose period starts on or after. */
  from?: string;
  /** ISO date: only figures whose period ends on or before. */
  to?: string;
  /** Calendar grouping — a LABEL per figure, never arithmetic. */
  bucket?: "day" | "week" | "month" | "quarter";
}

/**
 * GET /metrics/history (handoff 0023, design point 4): persisted figures
 * GROUPED by calendar bucket — the server never sums, averages, or derives
 * a number from grouped figures, and neither does this UI. Every point is
 * a full metric-value row verbatim with its metric_value_id receipt.
 */
export function getMetricsHistory(
  query: HistoryQuery = {},
): Promise<HistoryResponse> {
  const params = new URLSearchParams();
  if (query.metric) params.set("metric", query.metric);
  if (query.mode) params.set("mode", query.mode);
  if (query.scope) params.set("scope", query.scope);
  if (query.calc_version) params.set("calc_version", query.calc_version);
  if (query.from) params.set("from", query.from);
  if (query.to) params.set("to", query.to);
  if (query.bucket) params.set("bucket", query.bucket);
  const qs = params.toString();
  return request<HistoryResponse>(
    "GET",
    `/metrics/history${qs ? `?${qs}` : ""}`,
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
 * exists. Pass the branding bundle's logo_version so the URL changes when
 * the logo is replaced — the cache-busting fix for the first-UAT "can't
 * replace the logo" report (handoff 0025, design point 3): without it the
 * fixed URL + Cache-Control kept showing the OLD logo after a replacement.
 */
export function brandingLogoUrl(version?: string | null): string {
  const v = version ? `?v=${encodeURIComponent(version)}` : "";
  return `${BASE_URL}/branding/logo${v}`;
}

/**
 * DELETE /branding/logo (certifying official only — enforced server-side;
 * audited). "Remove it entirely" exists (handoff 0025): the header returns
 * to the display name alone. Refusals surface verbatim.
 */
export function deleteLogo(): Promise<LogoDeleteResponse> {
  return request<LogoDeleteResponse>("DELETE", "/branding/logo");
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

// ---- block labels (handoff 0038 / task #34) ----
//
// Both certifying_official-only, enforced server-side. The file is sent
// TWICE on purpose: preview derives and reports, load derives again from the
// exact bytes it writes. Nothing is cached between them, so an operator can
// never approve numbers that describe a different file from the one saved.

/** One row the derivation could not use, with the reason in plain words. */
export interface BlockLabelProblemRow {
  line: number;
  trip_name: string;
  block_name: string;
  reason: string;
}

/** What the upload concluded about one service day in the file. */
export interface ServiceDayNote {
  service_day: string;
  used: boolean;
  trips_named: number;
  explanation: string;
}

/** What an upload would do (preview) or did (load). Counts are complete;
 *  only the example lists are capped, and `examples_capped_at` says so. */
export interface BlockLabelPreview {
  rows_read: number;
  matched: number;
  ambiguous: number;
  unmatched: number;
  unparseable: number;
  labels_derived: number;
  conflicts: number;
  ambiguous_examples: BlockLabelProblemRow[];
  unmatched_examples: BlockLabelProblemRow[];
  unparseable_examples: BlockLabelProblemRow[];
  conflict_notes: string[];
  service_days: ServiceDayNote[];
  examples_capped_at: number;
  note: string;
}

/** POST /admin/block-labels/preview — reports only. Writes nothing. */
export function previewBlockLabels(file: File): Promise<BlockLabelPreview> {
  const form = new FormData();
  form.append("file", file);
  return request<BlockLabelPreview>("POST", "/admin/block-labels/preview", form);
}

/** POST /admin/block-labels/load — derives again and writes the mapping. */
export function loadBlockLabels(file: File): Promise<BlockLabelPreview> {
  const form = new FormData();
  form.append("file", file);
  return request<BlockLabelPreview>("POST", "/admin/block-labels/load", form);
}

// ---- users admin (handoff 0025, design point 1) ----
//
// ALL certifying_official-only, enforced server-side; every change is
// audited by the API. No endpoint ever returns password material.

/** GET /users — every account: username, role, active state, created. */
export function listUsers(): Promise<UserRecord[]> {
  return request<UserRecord[]>("GET", "/users");
}

/**
 * POST /users — create a local account. Validation is the installer's
 * (username charset; password >= 8 chars, <= 72 bytes) and the server's
 * plain-language refusals surface verbatim.
 */
export function createUser(
  body: CreateUserRequest,
): Promise<CreateUserResponse> {
  return request<CreateUserResponse>("POST", "/users", body);
}

/** POST /users/{username}/reset-password — admin sets a new password. */
export function resetUserPassword(
  username: string,
  password: string,
): Promise<ResetPasswordResponse> {
  return request<ResetPasswordResponse>(
    "POST",
    `/users/${encodeURIComponent(username)}/reset-password`,
    { password },
  );
}

/**
 * POST /users/{username}/deactivate. THE LOCKOUT FAIL-SAFE lives server-
 * side: deactivating the last active certifying official is refused (409)
 * and that refusal renders verbatim at the control.
 */
export function deactivateUser(
  username: string,
): Promise<ActiveChangeResponse> {
  return request<ActiveChangeResponse>(
    "POST",
    `/users/${encodeURIComponent(username)}/deactivate`,
  );
}

/** POST /users/{username}/reactivate. */
export function reactivateUser(
  username: string,
): Promise<ActiveChangeResponse> {
  return request<ActiveChangeResponse>(
    "POST",
    `/users/${encodeURIComponent(username)}/reactivate`,
  );
}

/**
 * POST /users/{username}/role — same last-admin guard as deactivation
 * (the server refuses demoting the last active certifying official).
 */
export function setUserRole(
  username: string,
  role: string,
): Promise<ChangeRoleResponse> {
  return request<ChangeRoleResponse>(
    "POST",
    `/users/${encodeURIComponent(username)}/role`,
    { role },
  );
}

// ---- calc runs (handoff 0026) ----

/**
 * POST /calc/runs (data_steward or above — enforced server-side; audited).
 * Asks the server to run the deterministic calculation service over one
 * half-open period. The server dispatches the SAME runner the CLI runs, in
 * the background; the 202 response is just the queued row — poll
 * getCalcRun for the truth. A second request while one run is live is a
 * 409 whose plain-language message names the live run; it renders verbatim
 * at the control. This UI never computes a figure.
 */
export function startCalcRun(body: CalcRunRequest): Promise<CalcRunCreated> {
  return request<CalcRunCreated>("POST", "/calc/runs", body);
}

/** GET /calc/runs — run history, newest first, bounded (any signed-in role). */
export function listCalcRuns(limit?: number): Promise<CalcRunRecord[]> {
  const qs =
    limit !== undefined
      ? `?${new URLSearchParams({ limit: String(limit) })}`
      : "";
  return request<CalcRunRecord[]>("GET", `/calc/runs${qs}`);
}

/** GET /calc/runs/{id} — one run; the poll target while a run is live. */
export function getCalcRun(runId: string): Promise<CalcRunRecord> {
  return request<CalcRunRecord>(
    "GET",
    `/calc/runs/${encodeURIComponent(runId)}`,
  );
}

// ---- data sources status (handoff 0025, design point 2) ----

/**
 * GET /sources/status (data_steward+ — enforced server-side): read-only —
 * what raw.records has actually seen per (source, connector), plus the
 * canonical vehicle-position liveness. There is NO add-source call because
 * no add-source API exists; the served connecting_note states how
 * connecting really works and the UI renders it verbatim.
 */
export function getSourcesStatus(
  windowHours?: number,
): Promise<SourcesStatusResponse> {
  const qs =
    windowHours !== undefined
      ? `?${new URLSearchParams({ window_hours: String(windowHours) })}`
      : "";
  return request<SourcesStatusResponse>("GET", `/sources/status${qs}`);
}

// ---- the raw-record inspector (handoff 0035) ----

/**
 * GET /raw/records/{id} — the label on the evidence bag. Every field is a
 * raw.records column or a measurement taken server-side; an absent value is
 * served absent and rendered absent.
 */
export function getRawRecord(recordId: string): Promise<RawRecordLabel> {
  return request<RawRecordLabel>(
    "GET",
    `/raw/records/${encodeURIComponent(recordId)}`,
  );
}

/**
 * POST /raw/records/{id}/verify — integrity as an action, not a claim.
 *
 * The ONE call in this client that reads the body on a non-2xx response,
 * deliberately: the API answers 409 for a mismatch and 404/410/503 for
 * unreadable bytes precisely so a caller checking only the status cannot
 * mistake a failure for a pass — and the failing body is the verdict the
 * auditor came for. A 401 still redirects to sign-in like every other call.
 */
export async function verifyRawRecord(
  recordId: string,
): Promise<RawRecordVerdict> {
  const path = `/raw/records/${encodeURIComponent(recordId)}/verify`;
  const session = getSession();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (session) headers["Authorization"] = `Bearer ${session.token}`;

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, { method: "POST", headers });
  } catch {
    throw new ApiError(NETWORK_ERROR_STATUS, NETWORK_ERROR_MESSAGE);
  }
  if (response.status === 401) {
    clearSession();
    unauthorizedHandler?.();
    throw new ApiError(401, "Your session has expired. Please sign in again.");
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError(response.status, UNREADABLE_ERROR_MESSAGE);
  }
  if (body && typeof body === "object" && "result" in body) {
    return body as RawRecordVerdict;
  }
  // No verdict in the body (403, 404 on an unknown record id, 5xx): surface
  // the server's plain-language message, never a fabricated verdict.
  const detail = (body as ErrorEnvelope | null)?.detail;
  throw new ApiError(
    response.status,
    typeof detail === "string" ? detail : UNREADABLE_ERROR_MESSAGE,
  );
}

/** GET /raw/records/{id}/payload — the bounded, decoded window. */
export function getRawRecordPayload(
  recordId: string,
): Promise<RawRecordPreview> {
  return request<RawRecordPreview>(
    "GET",
    `/raw/records/${encodeURIComponent(recordId)}/payload`,
  );
}

/**
 * GET /raw/records/{id}/download — the exact stored bytes. Saved byte for
 * byte (saveBlob re-encodes nothing), so hashing the saved file reproduces
 * the record id.
 */
export function downloadRawRecord(recordId: string): Promise<ExportDownload> {
  return requestExport(
    `/raw/records/${encodeURIComponent(recordId)}/download`,
    recordId,
  );
}

// ---- revenue review queue (handoff 0040) ----

/**
 * GET /revenue-review/boardings — one BOUNDED page of the boardings the
 * calculation held out of Unlinked Passenger Trips because it could not tell
 * prep from real riders.
 *
 * Paged on the server by keyset cursor, like the data-quality queue and for
 * the same reason: a queue that grows with the feed must never arrive as one
 * response, and a page must never skip or repeat a boarding while a
 * calculation run flags more behind the reader.
 */
export function listBoardingReviews(params?: {
  status?: string;
  limit?: number;
  cursor?: string;
}): Promise<BoardingReviewPage> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.cursor) query.set("cursor", params.cursor);
  const qs = query.toString();
  return request<BoardingReviewPage>(
    "GET",
    `/revenue-review/boardings${qs ? `?${qs}` : ""}`,
  );
}

/**
 * GET /revenue-review/boardings/counts — the whole-queue tally. The ONLY
 * source of a queue-wide number: no screen counts the rows it happens to
 * have loaded.
 */
export function getBoardingReviewCounts(): Promise<BoardingReviewCounts> {
  return request<BoardingReviewCounts>(
    "GET",
    "/revenue-review/boardings/counts",
  );
}

/** GET /revenue-review/boardings/{id} — one boarding, the deep-link target. */
export function getBoardingReview(
  passengerEventId: string,
): Promise<BoardingReview> {
  return request<BoardingReview>(
    "GET",
    `/revenue-review/boardings/${encodeURIComponent(passengerEventId)}`,
  );
}

/**
 * POST /revenue-review/boardings/{id}/classify — record one decision and the
 * reason for it. The reason is required by the API and by the database; this
 * client never sends a blank one, and the form never offers that path.
 *
 * The response does not mean a figure changed. It means a decision was
 * recorded; the figure moves when the calculation is next run.
 */
export function classifyBoarding(
  passengerEventId: string,
  body: ClassifyBoardingRequest,
): Promise<ClassifyBoardingResponse> {
  return request<ClassifyBoardingResponse>(
    "POST",
    `/revenue-review/boardings/${encodeURIComponent(passengerEventId)}/classify`,
    body,
  );
}

// ---------------------------------------------------------------------------
// Single sign-on (handoff 0046 / ADR-0011)
// ---------------------------------------------------------------------------
//
// Two audiences behind one section. The three sign-in calls are deliberately
// UNAUTHENTICATED (`auth: false`) — nobody is signed in yet, and attaching a
// stale bearer token to them would be meaningless at best. The configuration
// calls are ordinary authenticated admin calls, certifying-official only at
// the server.
//
// There is NO function here that reads a client secret back, because there is
// no endpoint that serves one. A stored secret is encrypted at rest and shown
// exactly once — at the moment the administrator typed it.

/** What the sign-in screen may know before anyone signs in. Nothing else. */
export interface SsoStatus {
  enabled: boolean;
  button_label: string;
}

export interface SsoStartResponse {
  authorization_url: string;
  state: string;
  /**
   * Keep in sessionStorage for the length of the redirect and send back at
   * the callback. In a bearer-token app there is no cookie to bind `state`
   * to, so this is what ties a sign-in to THIS browser.
   */
  browser_token: string;
}

export interface SsoCallbackRequest {
  code: string;
  state: string;
  browser_token: string;
}

export interface SsoCallbackResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  username: string;
  role: string;
}

export interface SsoConfig {
  configured: boolean;
  discovery_url: string | null;
  client_id: string | null;
  /** Whether a secret is stored. The secret itself is never served. */
  client_secret_set: boolean;
  redirect_uri: string | null;
  groups_claim: string;
  username_claim: string;
  clock_skew_seconds: number;
  ca_bundle_path: string | null;
  button_label: string;
  is_enabled: boolean;
  updated_by: string | null;
  updated_at: string | null;
  /** False when the server has no at-rest encryption key — warn BEFORE the
      administrator types a credential, not with a 503 afterwards. */
  secret_storage_available: boolean;
  disabled_by_environment: boolean;
}

export interface UpdateSsoConfigRequest {
  discovery_url: string;
  client_id: string;
  /** Omit to KEEP the stored secret; "" clears it. */
  client_secret?: string | null;
  redirect_uri: string;
  groups_claim: string;
  username_claim: string;
  clock_skew_seconds: number;
  ca_bundle_path: string | null;
  button_label: string;
  is_enabled: boolean;
}

export interface SsoConfigUpdated extends SsoConfig {
  audit_event_id: number;
}

export interface SsoTestStep {
  step: string;
  ok: boolean;
  message: string;
}

export interface SsoTestResult {
  ok: boolean;
  steps: SsoTestStep[];
  audit_event_id: number;
}

export interface SsoRoleMapping {
  mapping_id: string;
  claim_value: string;
  headway_role: string;
  role_label: string;
  note: string | null;
  created_by: string;
  created_at: string;
}

export interface CreateSsoMappingRequest {
  claim_value: string;
  headway_role: string;
  note?: string | null;
}

export interface SsoMappingCreated extends SsoRoleMapping {
  audit_event_id: number;
}

export interface SsoMappingDeleted {
  claim_value: string;
  headway_role: string;
  audit_event_id: number;
}

/** GET /auth/oidc/status — unauthenticated; enough to draw a button, no more. */
export function getSsoStatus(): Promise<SsoStatus> {
  return request<SsoStatus>("GET", "/auth/oidc/status", undefined, {
    auth: false,
  });
}

/**
 * POST /auth/oidc/start — begin an authorization-code + PKCE sign-in.
 * Unauthenticated. The caller sends the browser to `authorization_url` and
 * keeps `browser_token` until the provider sends it back.
 */
export function startSsoLogin(): Promise<SsoStartResponse> {
  return request<SsoStartResponse>("POST", "/auth/oidc/start", undefined, {
    auth: false,
  });
}

/**
 * POST /auth/oidc/callback — finish the sign-in and receive a Headway
 * session. Unauthenticated. Every failure returns one generic message; the
 * real reason is in Headway's audit trail, by design.
 */
export function finishSsoLogin(
  body: SsoCallbackRequest,
): Promise<SsoCallbackResponse> {
  return request<SsoCallbackResponse>(
    "POST",
    "/auth/oidc/callback",
    body,
    { auth: false },
  );
}

/** GET /auth/oidc/config — the stored settings, never the client secret. */
export function getSsoConfig(): Promise<SsoConfig> {
  return request<SsoConfig>("GET", "/auth/oidc/config");
}

/** PUT /auth/oidc/config — save the settings (audited; secret encrypted). */
export function updateSsoConfig(
  body: UpdateSsoConfigRequest,
): Promise<SsoConfigUpdated> {
  return request<SsoConfigUpdated>("PUT", "/auth/oidc/config", body);
}

/**
 * POST /auth/oidc/config/test — prove it works before anyone depends on it.
 * Runs the real sign-in code as far as it can go without a browser.
 */
export function testSsoConfig(): Promise<SsoTestResult> {
  return request<SsoTestResult>("POST", "/auth/oidc/config/test");
}

/** GET /auth/oidc/mappings — every configured group -> role grant. */
export function listSsoMappings(): Promise<SsoRoleMapping[]> {
  return request<SsoRoleMapping[]>("GET", "/auth/oidc/mappings");
}

/** POST /auth/oidc/mappings — grant a role to one exact group value. */
export function createSsoMapping(
  body: CreateSsoMappingRequest,
): Promise<SsoMappingCreated> {
  return request<SsoMappingCreated>("POST", "/auth/oidc/mappings", body);
}

/** DELETE /auth/oidc/mappings/{id} — remove a grant. Accounts are untouched. */
export function deleteSsoMapping(
  mappingId: string,
): Promise<SsoMappingDeleted> {
  return request<SsoMappingDeleted>(
    "DELETE",
    `/auth/oidc/mappings/${encodeURIComponent(mappingId)}`,
  );
}
