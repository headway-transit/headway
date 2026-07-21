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
  /**
   * The honesty boundary (handoff 0014, migration 0024): "ntd" for
   * regulatory figures, "ops" for operations metrics — which are NEVER
   * certifiable (a certified ops row is unrepresentable in the database),
   * never in the MR-20 package, and never in the public certified feed. The
   * UI badges every "ops" figure "Operations metric — not an NTD reported
   * figure". Optional so the UI tolerates an API that predates the field
   * (rows without it are NTD-era figures).
   */
  category?: string;
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
  /**
   * The certification block (handoff 0019, design 7): the public feed
   * serves the signing-key fingerprint — never the certifier's identity.
   * key_fingerprint is null on pre-signature (legacy) certifications;
   * the whole block is null/absent on an API that predates it.
   */
  certification?: {
    certification_id: string;
    /** ISO date-time */
    certified_at: string;
    key_fingerprint: string | null;
  } | null;
}

// ---- /certifications (handoff 0019, design B — the digital signature) ----
//
// Typed against services/api routers/certify.py EXACTLY (reconciled
// 2026-07-15 against the backend's parallel build of the same handoff:
// CertificationRequest/Response, CertificationRecord/Certificate,
// VerificationResult, IntentResponse). The original mock-first shapes
// (signer_name, a flat scope_statement, an acknowledgments array, a
// per-figure receipt_hash on MetricValue) were all corrected here — none
// silently: see handoff 0019's frontend evidence.

export interface CertificationRequest {
  /** minItems 1 */
  metric_value_ids: string[];
  /**
   * The intent statement the signer signed against, sent verbatim (the
   * server records it as the document's attestation_text — the permanent
   * record carries exactly the words the signer saw). The UI displays the
   * SERVER's statement (GET /certifications/intent), never its own.
   */
  attestation: string;
  /** The typed full name — the signing ceremony's deliberate act. */
  signer_full_name: string;
  /** The typed title. */
  signer_title: string;
}

export interface CertificationResponse {
  certification_id: string;
  metric_value_ids: string[];
  certified_by: string;
  /** ISO date-time */
  certified_at: string;
  attestation: string;
  signer_full_name: string;
  signer_title: string;
  /** The exact signed bytes (canonical JSON), as stored. */
  canonical_document: string;
  /** Base64 Ed25519 signature over canonical_document. */
  signature: string;
  key_fingerprint: string;
  algorithm?: string;
  audit_event_id: number;
}

/**
 * GET /certifications/intent — the fixed statements the signing ceremony
 * renders: the ESIGN-style intent statement the typed name/title are
 * entered against, and the honest-scope statement printed on the
 * certificate. SERVED BY THE BACKEND so the screen and the signed record
 * carry the same words; the UI never substitutes its own.
 */
export interface CertificationIntent {
  intent_statement: string;
  scope_statement: string;
  algorithm?: string;
}

/**
 * The statistician-attestation provenance a factored-beyond-2% figure
 * carries permanently (headway_calc attestation.to_provenance_dict —
 * detail.attestation on the figure, and the certificate document's
 * statistician_attestations entries). All values are JSON-safe strings.
 */
export interface AttestationProvenance {
  attestation_id: string;
  statistician_name: string;
  statistician_credentials: string;
  method_description: string;
  document_reference: string;
  metric: string;
  scope_pattern: string;
  /** ISO date */
  period_start: string;
  /** ISO date */
  period_end: string;
  entered_by: string;
  /** ISO date-time */
  entered_at: string;
  /** The verbatim p. 146 basis sentence the calc pinned. */
  basis?: string;
}

/**
 * One figure exactly as the signature covers it (the canonical document's
 * figures[]). Values are strings verbatim; receipt_sha256 is the figure's
 * receipt hash, independently recomputable from the served figure.
 */
export interface CertificateCoveredFigure {
  metric_value_id: string;
  metric: string;
  unit: string;
  /** ISO date */
  period_start: string;
  /** ISO date */
  period_end: string;
  scope: string;
  value: string;
  calc_name: string;
  calc_version: string;
  category?: string;
  detail?: Record<string, unknown>;
  /** SHA-256 receipt hash recorded in the signed document. */
  receipt_sha256: string;
}

/** The parsed canonical document (the exact signed content). */
export interface CertificationDocument {
  document_type: string;
  document_version: number;
  certification_id: string;
  /** ISO date-time */
  certified_at: string;
  certifier: {
    username: string;
    role: string;
    typed_full_name: string;
    typed_title: string;
  };
  /** The ESIGN-style intent statement, as signed. */
  intent_statement: string;
  /** The honest-scope statement (design 8), as signed — verbatim. */
  scope_statement: string;
  /** The request's attestation text, as signed. */
  attestation_text: string;
  figures: CertificateCoveredFigure[];
  statistician_attestations: AttestationProvenance[];
}

/**
 * GET /certifications/{id}/verify — the server re-verifies the STORED
 * document bytes against the STORED signature (and the document's binding
 * to this very row). `message` is the server's plain-language verdict,
 * shown verbatim in every direction — a failure is never softened.
 */
export interface VerificationResult {
  certification_id: string;
  signed: boolean;
  /** null for unsigned legacy records (nothing to verify). */
  verified: boolean | null;
  /** 'verified' | 'failed' | 'unsigned_legacy' | 'key_mismatch' */
  verdict: string;
  algorithm?: string;
  key_fingerprint?: string | null;
  /** ISO date-time */
  certified_at: string;
  message: string;
}

/** One certification as GET /certifications lists it. Legacy records
 *  (pre-signature) carry signed=false and null signer fields. */
export interface CertificationRecord {
  certification_id: string;
  metric_value_ids: string[];
  certified_by: string;
  /** ISO date-time */
  certified_at: string;
  attestation: string;
  signed: boolean;
  key_fingerprint: string | null;
  signer_full_name: string | null;
  signer_title: string | null;
}

/**
 * GET /certifications/{id} — the certificate view: the record plus the
 * raw signed bytes, the parsed document, and a LIVE verification result
 * computed by the server on every read.
 */
export interface CertificationCertificate extends CertificationRecord {
  canonical_document: string | null;
  signature: string | null;
  /** Parsed canonical document; null for legacy/unparseable (the
   *  verification result reports the failure loudly). */
  document: CertificationDocument | null;
  verification: VerificationResult;
}

// ---- /attestations (handoff 0019, design A — statistician attestations) ----
//
// Typed against services/api routers/attestations.py EXACTLY (reconciled
// 2026-07-15). Entry and revocation are certifying_official (the backend's
// documented smallest-honest-fit role choice); any signed-in role reads.
// Append-only: revocation sets the revocation trio, nothing is deleted.

export interface AttestationRequest {
  statistician_name: string;
  /** Plain-language summary of why this statistician is qualified. */
  statistician_credentials: string;
  /** The approved factoring method, in the statistician's terms. */
  method_description: string;
  /** External pointer to the approval document — never the document. */
  document_reference: string;
  /** upt | pmt — the p. 146 rule covers the 100%-count paths only. */
  metric: string;
  /**
   * fnmatch pattern over computed.metric_values.scope: 'agency',
   * 'mode:bus', 'mode:DR:tos:*', or '*' for every scope.
   */
  scope_pattern: string;
  /** ISO date — half-open [start, end) range the approval covers. */
  period_start: string;
  /** ISO date */
  period_end: string;
}

/** One recorded attestation. Revoked rows are served by default —
 *  revocation is history, not deletion. */
export interface AttestationRecord extends AttestationRequest {
  attestation_id: string;
  entered_by: string;
  /** ISO date-time */
  entered_at: string;
  /** ISO date-time, or null while the attestation stands. */
  revoked_at: string | null;
  revoked_by: string | null;
  revocation_reason: string | null;
}

/** POST /attestations 201 response (flat: the record + the audit id). */
export interface AttestationCreated extends AttestationRecord {
  audit_event_id: number;
}

/** POST /attestations/{id}/revoke body. */
export interface AttestationRevokeRequest {
  /** minLength 1 — kept in the record and the audit log. */
  reason: string;
}

/** POST /attestations/{id}/revoke response (flat). */
export interface AttestationRevoked extends AttestationRecord {
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

/**
 * GET /dq/issues/counts (handoff 0017, design point 2 — consumed by /today
 * per handoff 0021): counts computed over EXACTLY the rows GET /dq/issues
 * serves under the same filter, so a card total can never disagree with
 * the queue behind its door. Missing severities/statuses are explicit
 * zeros. Workflow tallies, never regulatory figures.
 */
export interface DqIssueCounts {
  total: number;
  by_severity: Record<string, number>;
  by_status: Record<string, number>;
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

/**
 * POST /dq/issues/{issue_id}/attest body (handoff 0019, migration 0029):
 * close ONE p. 146 refusal issue under a RECORDED statistician attestation.
 * The caller supplies only the reference — the resolution text is built
 * server-side from the attestation record, never typed here.
 */
export interface AttestRequest {
  /** minLength 1 — the attestation_id of a standing (unrevoked) record. */
  attestation_id: string;
}

/**
 * POST /dq/issues/{issue_id}/attest response. status is the explicit
 * 'attested' closed state — never a generic 'resolved', never a deletion.
 */
export interface AttestResponse {
  issue_id: string;
  status: string;
  /** ISO date-time */
  resolved_at: string;
  /** Server-built resolution text naming the attestation, verbatim. */
  resolution: string;
  attestation_id: string;
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
/**
 * Themed nav chrome (branding v2, handoff 0017 design point 7). Typed
 * against services/api's ChromeTheme EXACTLY (reconciled against the
 * regenerated openapi.json on 2026-07-14): ONE color set, validated
 * against itself by the server-side WCAG AA pair guardrail at write time
 * (header_fg on header_bg >= 4.5:1, accent on header_bg >= 4.5:1). The
 * shell applies it only in the display mode it was validated for (light);
 * dark mode keeps the neutral Headway chrome — the served chrome_note
 * states the rule.
 */
export interface BrandingChrome {
  /** '#rrggbb' — the header bar background. */
  header_bg: string;
  /** '#rrggbb' — header text/nav links; server-verified on header_bg. */
  header_fg: string;
  /** '#rrggbb' — the active-page accent; server-verified on header_bg. */
  accent: string;
}

export interface Branding {
  display_name: string;
  /** '#rrggbb'; server-verified >= 4.5:1 against both light app surfaces. */
  primary: string;
  /** '#rrggbb'; server-verified >= 4.5:1 against both light app surfaces. */
  accent: string;
  has_logo: boolean;
  /**
   * Branding v2 (handoff 0017): the themed chrome, or null/absent for the
   * neutral Headway default. Optional so the UI tolerates an API that
   * predates branding v2.
   */
  chrome?: BrandingChrome | null;
  /** The server's per-mode limitation statement, verbatim. */
  chrome_note?: string;
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

/**
 * GET /safety/events/counts (handoff 0017, design point 2 — consumed by
 * /today per handoff 0021): counted over EXACTLY the rows GET
 * /safety/events serves under the same filters. Classification is each
 * event's LATEST verdict; an unclassified event is counted as such (never
 * guessed); superseded events are counted separately AND inside their
 * classification bucket, exactly as the list shows them. Workflow
 * tallies, never regulatory figures.
 */
export interface SafetyEventCounts {
  total: number;
  by_classification: Record<string, number>;
  unclassified: number;
  superseded: number;
}

// ---- /sampling (handoff 0012 — NTD sampling support v0) ----
//
// Typed against services/api routers/sampling.py's request/response
// models EXACTLY (PlanCreate/PlanRecord/PlanCreated, DrawRequest/
// DrawRecord/DrawCreated, MeasurementCreate/MeasurementRecord/
// MeasurementCreated, PlanProgress, EstimateRequest/EstimateBlock/
// EstimateResponse, OptionsResponse). The router was built in parallel
// against the same handoff; if it changes, the Backend Engineer issues a
// new handoff and these are updated against the new export — never
// guessed.

/**
 * GET /sampling/options — the plan wizard's vocabulary, straight from the
 * sampling_v0 calc selector's constants (Table 41.01 / §41.07), plus the
 * §41.01/§41.03 eligibility guidance and the p. 150 retention note. Every
 * string is the calc's own text, shown verbatim.
 */
export interface SamplingOptions {
  /** NTD mode code → plain-language mode-group label. */
  modes: Record<string, string>;
  /** NTD mode code → the units Table 41.01 allows for that mode. */
  units_by_mode: Record<string, string[]>;
  /** All efficiency-option tokens the selector knows (§41.07(c)). */
  efficiency_options: string[];
  /** The subset the API will actually create plans for (aptl, base). */
  creatable_options: string[];
  /** quarterly | monthly | weekly (§41.07(d)). */
  frequencies: string[];
  /** Weekday | Saturday | Sunday (§83.01(b) day-type estimates). */
  service_day_types: string[];
  /** The calc's §41.01/§41.03/p. 149 guidance strings, verbatim. */
  eligibility_guidance: string[];
  /** The calc's p. 150 ≥3-year documentation-retention note, verbatim. */
  retention_note: string;
}

/** POST /sampling/plans request body (router PlanCreate). */
export interface SamplingPlanRequest {
  /** The NTD report year this plan samples for (2000–2100). */
  report_year: number;
  /** NTD mode code per Table 41.01: DR, VP, MB, TB, CR, LR, HR, MR, AG. */
  mode: string;
  /** e.g. DO (directly operated) or PT (purchased transportation). */
  type_of_service: string;
  /** vehicle_days | one_way_trips | round_trips | one_way_car_trips | one_way_train_trips */
  unit: string;
  /** aptl | base (aptl_grouped cells are read-only reference). */
  efficiency_option: string;
  /** quarterly | monthly | weekly */
  frequency: string;
}

/**
 * A sampling plan as the API serves it (router PlanRecord).
 * required_per_period and required_annual are BOTH verbatim table cells
 * (whole service-unit counts — exact as JSON integers, never derived from
 * each other); table_citation and selector_version are the calc's own
 * strings, shown verbatim.
 */
export interface SamplingPlanRecord {
  plan_id: string;
  report_year: number;
  mode: string;
  type_of_service: string;
  unit: string;
  efficiency_option: string;
  frequency: string;
  /** The "<unit> for a <period>" table row, verbatim. */
  required_per_period: number;
  /** The "Total Sample Size for Year" table row, verbatim. */
  required_annual: number;
  /** The calc's citation for the table cell (table, column, both rows). */
  table_citation: string;
  /** e.g. "sampling_v0 0.1.0" — displayed verbatim, never parsed. */
  selector_version: string;
  /** created (no draw yet) | active — shown raw if unknown. */
  status: string;
  created_by: string;
  /** ISO date-time */
  created_at: string;
}

/** POST /sampling/plans 201 response (router PlanCreated). */
export interface SamplingPlanCreated {
  plan: SamplingPlanRecord;
  /** The calc's eligibility guidance + option caveats, verbatim. */
  guidance: string[];
  /** The calc's p. 150 retention note, verbatim. */
  retention_note: string;
  audit_event_id: number;
}

/**
 * POST /sampling/plans/{id}/draws body (router DrawRequest): ONE
 * random-selection act for ONE period at the plan's frequency. The
 * service-unit list must be ALL units expected to operate in the period
 * (§63.07), period-qualified so ids never repeat across periods. seed is
 * optional — blank lets the API generate one from a cryptographic source;
 * either way it is RECORDED for reproducibility.
 */
export interface SamplingDrawRequest {
  /** e.g. 2026-Q1, 2026-01, 2026-W14 — one draw per period. */
  period_label: string;
  service_units: string[];
  /** Optional (min 8 chars when given); recorded either way. */
  seed?: string;
  /** Extra randomly-drawn units beyond the per-period size (default 0). */
  oversample_units?: number;
}

/** One recorded draw (router DrawRecord). */
export interface SamplingDrawRecord {
  draw_id: string;
  plan_id: string;
  period_label: string;
  /** How many units were in the provided list (the sampling frame). */
  frame_size: number;
  /** The selected units IN DRAW ORDER — the ride checker's list. */
  selected_units: string[];
  /** The recorded seed (§63.03 reproducibility anchor). */
  seed: string;
  required_per_period: number;
  oversample_units: number;
  /** e.g. "sampling_v0 0.1.0" — displayed verbatim. */
  drawer_version: string;
  drawn_by: string;
  /** ISO date-time */
  drawn_at: string;
}

/** POST /sampling/plans/{id}/draws 201 response (router DrawCreated). */
export interface SamplingDrawCreated {
  draw: SamplingDrawRecord;
  /** The calc's documented §63.03 draw procedure, verbatim. */
  method: string;
  /** The oversampling-only-if-random citation when oversampling; else null. */
  oversampling_note: string | null;
  retention_note: string;
  audit_event_id: number;
}

/**
 * POST /sampling/plans/{id}/measurements body (router MeasurementCreate):
 * one ride-check observation for one drawn unit. observed_pmt is a
 * decimal STRING (exact NUMERIC, never a float) — the MetricValue.value
 * discipline; this UI never parses it.
 */
export interface SamplingMeasurementRequest {
  unit_id: string;
  /** Whole boardings counted by the ride checker. */
  observed_upt: number;
  /** Decimal-string passenger miles measured on this unit. */
  observed_pmt: string;
  /** Weekday | Saturday | Sunday — needed only for day-type estimates. */
  service_day_type?: string | null;
  /** ISO date the ride check was performed. */
  service_date?: string | null;
  notes?: string | null;
}

/** One recorded observation (router MeasurementRecord). Append-only:
 *  corrections supersede via superseded_by; originals never change. */
export interface SamplingMeasurementRecord {
  measurement_id: string;
  plan_id: string;
  unit_id: string;
  observed_upt: number;
  /** Exact NUMERIC as a JSON string, never a float. */
  observed_pmt: string;
  service_day_type: string | null;
  /** ISO date */
  service_date: string | null;
  /** e.g. "manual_ride_check" — provenance of the observation. */
  data_source: string;
  notes: string | null;
  entered_by: string;
  /** ISO date-time */
  entered_at: string;
  /** measurement_id of the correction, or null while this one stands. */
  superseded_by: string | null;
}

/** POST /sampling/plans/{id}/measurements 201 response. */
export interface SamplingMeasurementCreated {
  measurement: SamplingMeasurementRecord;
  /** The manual-entry caveat, verbatim. */
  source_caveat: string;
  retention_note: string;
  audit_event_id: number;
}

/** Per-draw progress (router DrawProgress) — API-computed workflow counts. */
export interface SamplingDrawProgress {
  period_label: string;
  selected: number;
  measured: number;
  oversample_units: number;
}

/**
 * GET /sampling/plans/{id}/progress (router PlanProgress): measured vs
 * required, per draw and overall, with the worksheet of
 * drawn-but-unmeasured units. undersampled and every count are computed
 * BY THE API; the citations are its verbatim regulatory text.
 */
export interface SamplingPlanProgress {
  plan: SamplingPlanRecord;
  required_per_period: number;
  required_annual: number;
  draws: SamplingDrawProgress[];
  units_selected: number;
  units_measured: number;
  /** Drawn units still needing a ride check, in draw order. */
  units_unmeasured: string[];
  undersampled: boolean;
  /** The API's no-undersampling citation (p. 149 quotes), verbatim. */
  undersampling_citation: string;
  /** The API's oversampling-only-if-random citation, verbatim. */
  oversampling_citation: string;
  retention_note: string;
}

/**
 * POST /sampling/plans/{id}/estimate body (router EstimateRequest). The
 * expansion factor IS the agency's 100% count of annual UPT (§83.01(a)),
 * supplied as a decimal STRING. upt_100pct_by_day_type additionally
 * requests per-day-type estimates (§83.01(b)) — not offered by this UI
 * in v0 (day-type blocks are still rendered if the API serves them).
 */
export interface SamplingEstimateRequest {
  annual_upt_100pct: string;
  upt_100pct_by_day_type?: Record<string, string>;
}

/**
 * One §83 estimate block (router EstimateBlock — the calc's
 * SampledPmtEstimate verbatim). Every figure except the whole counts is a
 * decimal STRING; method is the calc's fixed sampled-estimate provenance
 * label.
 */
export interface SamplingEstimateBlock {
  /** 'annual' or a service-day type (Weekday/Saturday/Sunday). */
  scope: string;
  sample_size: number;
  sample_total_upt: number;
  /** Σ observed PMT over the sample, decimal string verbatim. */
  sample_total_pmt: string;
  /** Ratio of totals (§83.05(a)), decimal string verbatim. */
  sample_aptl: string;
  /** The 100% UPT expansion factor (§83.01), echoed verbatim. */
  expansion_factor_upt: string;
  /** expansion factor × sample APTL (§83.07), verbatim — the estimate. */
  estimated_pmt: string;
  /** The calc's fixed provenance label — a SAMPLED ESTIMATE. */
  method: string;
}

/** POST /sampling/plans/{id}/estimate response (router EstimateResponse). */
export interface SamplingEstimateResponse {
  plan_id: string;
  estimate: SamplingEstimateBlock;
  by_service_day: SamplingEstimateBlock[] | null;
  units_measured: number;
  required_annual: number;
  /** measured − required (random oversampling; 0 when exactly on target). */
  oversampled_by: number;
  /** The API's caveats (sampled-estimate, manual-entry, …), verbatim. */
  caveats: string[];
  /** The API's §83 citations + the plan's table citation, verbatim. */
  citations: string[];
  retention_note: string;
  audit_event_id: number;
}

// ---- /metrics/compare (handoff 0017, design point 1) ----
//
// Typed against services/api routers/metrics.py's compare models EXACTLY
// (Comparand/CompareCell/CompareRow/CompareResponse — reconciled against
// the regenerated openapi.json on 2026-07-14; the endpoint was built in
// parallel against the same handoff and landed while this UI was in
// flight). The endpoint COMPOSES the same reader as GET /metrics/values —
// it never computes a figure; deltas are exact server-side Decimal
// differences served as signed strings.

/**
 * One comparison column, echoed back exactly as parsed from the request
 * token: '<period_start>..<period_end>' optionally followed by
 * '@<calc_name>:<calc_version>'. The FIRST comparand is the baseline.
 */
export interface CompareComparand {
  /** The request token, echoed. */
  key: string;
  /** ISO date */
  period_start: string;
  /** ISO date */
  period_end: string;
  /** The pinned calculation, or null when the comparand pinned none. */
  calc_name?: string | null;
  calc_version?: string | null;
  baseline: boolean;
}

/**
 * One (scope, comparand) cell: the FULL MetricValue row (verbatim — the
 * receipt affordance needs metric_value_id; badges need detail/category/
 * certification_status) or an explicit missing reason, plus the exact
 * deltas. This UI never subtracts two figures.
 */
export interface CompareCell {
  comparand_index: number;
  value?: MetricValue | null;
  /** A missing figure is shown as missing, never invented. */
  missing_reason?: string | null;
  /** Exact signed Decimal string vs the baseline cell; null when either
   *  side is missing or for the baseline column itself. */
  delta_vs_baseline?: string | null;
  delta_vs_previous?: string | null;
}

export interface CompareRow {
  scope: string;
  cells: CompareCell[];
}

/** GET /metrics/compare response. */
export interface CompareResponse {
  metric: string;
  /** The unit shared by every present cell — null when no cell is present. */
  unit: string | null;
  comparands: CompareComparand[];
  /** Row order: 'agency' first, the rest sorted (unless requested). */
  scopes: string[];
  rows: CompareRow[];
  /**
   * Direction metadata from the CALC LIBRARY's metric registry (handoff
   * 0017: registry, never per-view; only 'coverage' is registered today,
   * as 'higher_is_better'). null = sign-neutral: a delta on such a metric
   * is a difference, not a win.
   */
  directions: Record<string, string | null>;
  /** The registry's own explanation, verbatim. */
  direction_note: string;
  /** The server's delta provenance note, verbatim. */
  delta_note: string;
  /** True when present cells mix certified and uncertified figures. */
  mixed_certification: boolean;
  /** The server's label-both note, verbatim; null when not mixed. */
  mixed_certification_note: string | null;
}

// ---- /sandbox/preview (handoff 0017, design point 6) ----
//
// Typed against services/api routers/sandbox.py EXACTLY (reconciled against
// the regenerated openapi.json on 2026-07-14). The preview entry points
// perform NO writes; `persisted` is a constant false, previews are
// EPHEMERAL (the handoff's category='ops'-rows alternative was rejected by
// the backend as the less honest design — documented in the router).

export interface SandboxPreviewRequest {
  /** ISO date */
  period_start: string;
  /** ISO date */
  period_end: string;
  /**
   * Proposed knob values keyed by settings key (>= 1 entry). Values are
   * STRINGS exactly like the settings surface — decimals parse via
   * Decimal server-side; floating point never touches a policy number.
   */
  proposed: Record<string, string>;
}

/**
 * One variant's outcome for one metric: the would-be value (or an honest
 * refusal — `blocked` with the would-be findings) plus the would-be
 * calculation detail. Nothing here was written anywhere.
 */
export interface PreviewSide {
  /** Decimal string verbatim, or null when the variant refused. */
  value: string | null;
  blocked: boolean;
  /** Would-be calc findings (Finding.to_dict(): issue_type, title,
   *  description, severity, source_record_ids). Shown, never hidden. */
  findings: Record<string, unknown>[];
  detail: Record<string, unknown> | null;
}

/** One impact-rail row: baseline (current audited settings) vs proposed. */
export interface PreviewMetricImpact {
  metric: string;
  calc_name: string;
  calc_version: string;
  unit: string;
  scope: string;
  /** 'ntd' | 'ops' — the honesty boundary carries through previews. */
  category: string;
  baseline: PreviewSide;
  proposed: PreviewSide;
  /** Exact Decimal difference proposed − baseline, as a string; null when
   *  either side has no value. */
  delta: string | null;
}

/** One knob family's preview (NTD calc-policy knobs, or the OTP ops knobs). */
export interface PreviewSection {
  /** The audited settings the baseline ran under, verbatim strings. */
  baseline_thresholds: Record<string, string>;
  /** Where each baseline value came from (setting/default), verbatim. */
  baseline_threshold_sources: Record<string, string>;
  proposed_thresholds: Record<string, string>;
  /** Input row counts the preview read (workflow counts). */
  inputs: Record<string, number>;
  metrics: PreviewMetricImpact[];
  derivation?: Record<string, unknown> | null;
}

export interface SandboxPreviewResponse {
  /** The server's own changes-nothing statement, verbatim. */
  banner: string;
  /** Constant false — previews are ephemeral, pinned by calc test. */
  persisted: boolean;
  /** ISO date */
  period_start: string;
  /** ISO date */
  period_end: string;
  /** The half-open-period convention, stated verbatim. */
  period_convention: string;
  /** The proposed knob values, echoed verbatim. */
  proposed: Record<string, string>;
  /** The server's pointer at the audited settings flow, verbatim. */
  settings_flow_note: string;
  /** Present when any NTD calc-policy knob was proposed. */
  ntd?: PreviewSection | null;
  /** Present when any OTP-window ops knob was proposed. */
  ops?: PreviewSection | null;
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
