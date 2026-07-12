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
  /**
   * Minutes a steward reported spending on the resolution — EFFORT METADATA
   * about the workflow, never a reported regulatory figure. Optional so the
   * UI tolerates an API that predates the field.
   */
  resolution_minutes?: number | null;
}

export interface ResolveRequest {
  /** minLength 1 */
  resolution: string;
  /** Optional whole minutes spent resolving (effort metadata). */
  resolution_minutes?: number;
}

export interface ResolveResponse {
  issue_id: string;
  status: string;
  /** ISO date-time */
  resolved_at: string;
  resolution: string;
  /** Echoed effort metadata; optional for an API that predates the field. */
  resolution_minutes?: number | null;
  audit_event_id: number;
}

// ---- /reports/mr20 ----

/**
 * One MR-20 cell (GET /reports/mr20). `value` is a JSON STRING verbatim
 * (never a float) or null; a null cell carries a plain-language `reason`.
 * `flags` are machine codes (e.g. "pending_d2" on rail cells awaiting the
 * D-2 form definition) that the UI translates to labels, never hides.
 */
export interface Mr20Cell {
  value: string | null;
  unit: string;
  metric_value_id: string | null;
  calc_name: string | null;
  calc_version: string | null;
  certification_status: string | null;
  flags: string[];
  /** Ratio string (e.g. "0.9126"), when the calculation reported one. */
  coverage?: string | null;
  /** Plain-language reason, present when value is null. */
  reason?: string | null;
}

/** The four MR-20 measures, for fleet and for each mode. */
export interface Mr20Cells {
  upt?: Mr20Cell;
  vrm?: Mr20Cell;
  vrh?: Mr20Cell;
  voms?: Mr20Cell;
}

/**
 * GET /reports/mr20?month=YYYY-MM — the MR-20 package. `reportable` is
 * false today and `banner` states why; the UI renders banner, citation,
 * caveats, and every cell VERBATIM, and the JSON download is the fetched
 * response byte for byte.
 */
export interface Mr20Package {
  form: string;
  /** YYYY-MM */
  month: string;
  /** ISO date */
  period_start: string;
  /** ISO date */
  period_end: string;
  citation: string;
  reportable: boolean;
  banner: string;
  caveats: string[];
  fleet: Mr20Cells;
  modes: Record<string, Mr20Cells>;
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

// ---- /safety (handoff 0010 — Safety & Security module v0) ----
//
// Typed against services/api routers/safety.py's response models EXACTLY
// (SafetyEventCreate/Created/Superseded/Record, ClassificationResult,
// Ss40Deadline/Ss50Deadline/DeadlinesResponse). If the router changes, the
// Backend Engineer issues a new handoff and these are updated against the
// new export — never guessed.

/** The classifier's verdict — sscls_v0 (calc-discipline code, Exhibit 5). */
export type SafetyClassification = "major" | "non_major" | "not_reportable";

/**
 * POST /safety/events request body (router SafetyEventCreate): the
 * threshold-supporting fields of migration 0017's safety.events.
 * property_damage_usd is a decimal STRING (exact NUMERIC, never a float) —
 * the same discipline as MetricValue.value; this UI never parses it.
 */
export interface SafetyEventRequest {
  /** ISO date-time WITH a timezone (the API refuses a naive timestamp). */
  occurred_at: string;
  /**
   * Headway's canonical mode vocabulary (the transform's GTFS
   * route_type→mode map — the same strings the classifier's rail test
   * uses). Agency-supplied per the manual's Predominant Use Rule (p. 15).
   */
  mode: string;
  type_of_service?: string | null;
  /** collision | derailment | fire | evacuation | security | assault | cyber | other */
  event_category: string;
  narrative: string;
  location?: string | null;
  fatalities: number;
  /** Immediate-transport definition (Exhibit 5): people, not severity guesses. */
  injuries: number;
  /** Decimal string, e.g. "30000.00"; null/absent = not (yet) assessed. */
  property_damage_usd?: string | null;
  /** Rail criteria (Exhibit 5, p. 16). */
  serious_injury?: boolean;
  /** Rail (Exhibit 5, p. 16); for cyber events: the intrusion disrupted operations. */
  substantial_damage?: boolean;
  towed?: boolean;
  evacuation_life_safety?: boolean;
  assault_on_worker?: boolean;
  involves_transit_vehicle?: boolean;
  involves_second_rail_vehicle?: boolean;
  grade_crossing?: boolean;
  /** Rail (migration 0018): uncommanded/uncontrolled/unmanned movement. */
  runaway_train?: boolean;
  /** Rail (migration 0018): evacuation to the controlled rail ROW. */
  evacuation_to_rail_row?: boolean;
}

/**
 * POST /safety/events/{id}/supersede body (router SupersedeRequest): the
 * corrected event PLUS the required reason, kept in the audit log — the
 * original event itself is never edited.
 */
export interface SafetySupersedeRequest extends SafetyEventRequest {
  reason: string;
}

/** One met threshold (or non-major basis), explained by the classifier. */
export interface ThresholdExplanation {
  /** Machine token (threshold_id / basis id in headway_calc/sscls.py). */
  threshold: string;
  /** The classifier's plain-language sentence, shown verbatim. */
  plain_language: string;
  /** The classifier's citation pointer, shown verbatim. */
  citation: string;
}

/**
 * The classifier's verdict as the entry/supersede response carries it
 * (router ClassificationResult). thresholds_met tokens are machine codes;
 * the UI maps known tokens to the verified manual quotes and shows unknown
 * tokens raw, never hidden. Every plain_language / citation / summary
 * string is the classifier's own text, shown verbatim.
 */
export interface SafetyClassificationResult {
  classification: SafetyClassification;
  /** Major thresholds only, in the classifier's fixed evaluation order. */
  thresholds_met: string[];
  explanations: ThresholdExplanation[];
  /** Why a non-major event belongs on the S&S-50 (empty otherwise). */
  non_major_basis: ThresholdExplanation[];
  /** 'collision' for an assault with transit-vehicle contact (Scenario E). */
  effective_category: string;
  is_rail_mode: boolean;
  /** One plain-language sentence for the entry response, shown verbatim. */
  summary: string;
  classifier_version: string;
}

/** POST /safety/events 201 response (router SafetyEventCreated). */
export interface SafetyEventCreated {
  event_id: string;
  /** ISO date-time */
  entered_at: string;
  result: SafetyClassificationResult;
  audit_event_id: number;
}

/** POST /safety/events/{id}/supersede 201 response. */
export interface SafetyEventSuperseded {
  original_event_id: string;
  replacement_event_id: string;
  /** ISO date-time */
  entered_at: string;
  result: SafetyClassificationResult;
  audit_event_id: number;
}

/**
 * One recorded event as GET /safety/events serves it (router
 * SafetyEventRecord — classification fields FLAT and nullable; the rich
 * explanations exist only on the entry response). Corrections are
 * append-only: a corrected event carries superseded_by and is NEVER
 * deleted — the UI must keep it visible (struck and linked), because
 * hiding it would break the audit story.
 */
export interface SafetyEventRecord {
  event_id: string;
  /** ISO date-time */
  occurred_at: string;
  mode: string;
  type_of_service: string | null;
  event_category: string;
  narrative: string;
  location: string | null;
  fatalities: number;
  injuries: number;
  /** Exact NUMERIC as a JSON string, never a float; null = not assessed. */
  property_damage_usd: string | null;
  serious_injury: boolean;
  substantial_damage: boolean;
  towed: boolean;
  evacuation_life_safety: boolean;
  assault_on_worker: boolean;
  involves_transit_vehicle: boolean;
  involves_second_rail_vehicle: boolean;
  grade_crossing: boolean;
  runaway_train: boolean;
  evacuation_to_rail_row: boolean;
  entered_by: string;
  /** ISO date-time */
  entered_at: string;
  /** event_id of the correcting event, or null while this record stands. */
  superseded_by: string | null;
  classification: string | null;
  thresholds_met: string[] | null;
  classifier_version: string | null;
  /** ISO date-time */
  classified_at: string | null;
}

/**
 * GET /safety/deadlines — computed BY THE API (occurred_at + 30 days for
 * S&S-40 per Exhibit 2; end of the following month for S&S-50 per Exhibit
 * 3, INCLUDING zero-event rows for every operated mode). The UI derives
 * only presentation urgency (days between the served due date and today —
 * calendar workflow math, never a regulatory figure).
 */
export interface Ss40Deadline {
  event_id: string;
  /** ISO date-time of the event the report covers. */
  occurred_at: string;
  mode: string;
  event_category: string;
  /** ISO date, API-computed: occurred_at + 30 days (Exhibit 2, p. 4). */
  due_date: string;
}

export interface Ss50Deadline {
  /** YYYY-MM reporting month. */
  month: string;
  mode: string;
  /** ISO date, API-computed: end of the following month (Exhibit 3, p. 5). */
  due_date: string;
  /** Unsuperseded non-major events for this month/mode (workflow count). */
  non_major_event_count: number;
  /** The manual's trap: a zero-event row is STILL due. */
  zero_event: boolean;
}

/** GET /safety/deadlines response (router DeadlinesResponse). */
export interface SafetyDeadlines {
  /** The YYYY-MM month the ss50 rows cover (S&S-40s are month-independent). */
  month: string;
  ss40: Ss40Deadline[];
  /** The API's citation text, shown verbatim where useful. */
  ss40_citation: string;
  /** Semantics caveat (v0 has no submission tracking), shown verbatim. */
  ss40_note: string;
  ss50: Ss50Deadline[];
  ss50_citation: string;
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
