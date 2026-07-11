/**
 * Hand-written TypeScript types matching services/api/openapi.json exactly
 * (Headway API 0.1.0). If the contract changes, the Backend Engineer issues a
 * new handoff and these types are updated against the new export — never
 * guessed.
 */

/** Roles from the API's verified claim set (services/api authz). */
export type Role =
  | "viewer"
  | "data_steward"
  | "report_preparer"
  | "certifying_official";

// ---- /auth/login ----

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  /** default "bearer" */
  token_type?: string;
  expires_in: number;
  username: string;
  role: string;
}

// ---- /metrics/values ----

export interface MetricValue {
  metric_value_id: string;
  metric: string;
  unit: string;
  /** ISO date */
  period_start: string;
  /** ISO date */
  period_end: string;
  scope: string;
  /**
   * A reported figure. The API serializes it as a JSON STRING (exact
   * NUMERIC, never float) and this UI keeps it a string end to end:
   * it is displayed verbatim and NEVER parsed into a number.
   */
  value: string;
  calc_name: string;
  calc_version: string;
  /** ISO date-time */
  computed_at: string;
  certification_status: string;
  /**
   * Per-value calculation detail (computed.metric_values.detail JSONB,
   * migration 0010; served since the wave-8 additive contract extension —
   * see handoff 0001's wave-8 response). `{}` for detail-less rows. Shapes
   * come from services/calc/headway_calc/types.py to_dict(): coverage
   * details for vrm/vrh, UptDetail for upt. Ratios/factors inside are JSON
   * STRINGS for the same reason `value` is — this UI never parses them into
   * numbers. Optional so the UI tolerates an API that predates the field.
   */
  detail?: Record<string, unknown>;
}

// ---- /metrics/values/{id}/lineage ----

/**
 * One node of the provenance tree. transform_name/transform_version describe
 * the transform that PRODUCED this node from its inputs. Raw records are
 * leaves: no transform, no inputs.
 */
export interface LineageNode {
  kind: string;
  id: string;
  transform_name?: string | null;
  transform_version?: string | null;
  /** default [] */
  inputs?: LineageNode[];
}

// ---- /public/metrics/certified ----

/**
 * A certified figure in publishable form (services/api routers/public.py,
 * handoff 0006 design point 8): the same shape as MetricValue — value is a
 * string verbatim, detail served verbatim with any simulated flags — with no
 * PII and no certifier identity. certification_status is always "certified".
 * certified_at is NOT served today; it is optional here so the UI shows a
 * certification date the moment the API starts serving one, never guesses it.
 */
export interface PublicMetricValue extends MetricValue {
  /** ISO date-time; not yet served by the API — rendered only when present. */
  certified_at?: string;
}

// ---- /certifications ----

export interface CertificationRequest {
  /** minItems 1 */
  metric_value_ids: string[];
  /** minLength 1 */
  attestation: string;
}

export interface CertificationResponse {
  certification_id: string;
  metric_value_ids: string[];
  certified_by: string;
  /** ISO date-time */
  certified_at: string;
  attestation: string;
  audit_event_id: number;
}

// ---- /dq/issues ----

export interface DqIssue {
  issue_id: string;
  issue_type: string;
  severity: string;
  status: string;
  owner: string | null;
  title: string;
  description: string;
  source_record_ids: string[] | null;
  /** ISO date-time */
  created_at: string;
  /** ISO date-time */
  resolved_at: string | null;
  resolution: string | null;
}

export interface ResolveRequest {
  /** minLength 1 */
  resolution: string;
}

export interface ResolveResponse {
  issue_id: string;
  status: string;
  /** ISO date-time */
  resolved_at: string;
  resolution: string;
  audit_event_id: number;
}

// ---- /branding + /settings (handoff 0008, pillar C) ----

/**
 * GET /branding (services/api routers/branding.py BrandingResponse):
 * UNAUTHENTICATED by design — the app shell brands itself before sign-in.
 * The two colors have already passed the server-side WCAG AA contrast
 * guardrail at write time (headway_api/branding.py).
 */
export interface Branding {
  display_name: string;
  /** '#rrggbb'; server-verified >= 4.5:1 against both light app surfaces. */
  primary: string;
  /** '#rrggbb'; server-verified >= 4.5:1 against both light app surfaces. */
  accent: string;
  has_logo: boolean;
}

/** One row of app.settings (services/api routers/settings.py Setting). */
export interface Setting {
  setting_key: string;
  /** Always a string, exactly as stored — never a JSON number. */
  setting_value: string;
  value_type: string;
  description: string;
  updated_by: string;
  /** ISO date-time */
  updated_at: string;
}

/** PUT /settings/{key} response (UpdateSettingResponse). */
export interface UpdateSettingResponse extends Setting {
  audit_event_id: number;
}

/** POST /branding/logo response (LogoUploadResponse). */
export interface LogoUploadResponse {
  content_type: string;
  bytes: number;
  audit_event_id: number;
}

// ---- error envelopes (FastAPI) ----

export interface ValidationErrorItem {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

/** 4xx bodies are {"detail": string} for HTTPException, or a list for 422. */
export interface ErrorEnvelope {
  detail?: string | ValidationErrorItem[];
}
