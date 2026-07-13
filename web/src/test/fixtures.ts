import type {
  DqIssue,
  LineageNode,
  MetricValue,
  Mr20Package,
  SafetyClassificationResult,
  SafetyEventCreated,
  SafetyEventRecord,
  SafetyEventSuperseded,
  SamplingDrawCreated,
  SamplingDrawRecord,
  SamplingEstimateResponse,
  SamplingMeasurementRecord,
  SamplingOptions,
  SamplingPlanCreated,
  SamplingPlanProgress,
  SamplingPlanRecord,
} from "../api/types";

/** Values as the API serves them: `value` is a decimal STRING, never a number. */
export const vrmValue: MetricValue = {
  metric_value_id: "mv-vrm-1",
  metric: "vrm",
  unit: "miles",
  period_start: "2026-03-01",
  period_end: "2026-03-31",
  scope: "agency",
  value: "12345.60", // trailing zero on purpose: must render verbatim
  calc_name: "vrm_v0",
  calc_version: "0.1.0",
  computed_at: "2026-04-01T06:00:00Z",
  certification_status: "uncertified",
};

export const vrhValue: MetricValue = {
  metric_value_id: "mv-vrh-1",
  metric: "vrh",
  unit: "hours",
  period_start: "2026-03-01",
  period_end: "2026-03-31",
  scope: "agency",
  value: "987.25",
  calc_name: "vrh_v0",
  calc_version: "0.1.0",
  computed_at: "2026-04-01T06:00:00Z",
  certification_status: "uncertified",
};

export const certifiedValue: MetricValue = {
  ...vrmValue,
  metric_value_id: "mv-vrm-0",
  period_start: "2026-02-01",
  period_end: "2026-02-28",
  value: "11111.10",
  certification_status: "certified",
};

/**
 * detail JSONB shapes exactly as services/calc/headway_calc/types.py
 * to_dict() persists them: ratios/factors are STRINGS, counts are ints,
 * gap/layover thresholds are JSON numbers.
 */

/** CoverageDetail shape (vrm/vrh calc 0.2.0+). */
export const vrmCoverageDetail = {
  coverage: "0.9126",
  total_groups: 2313,
  excluded_groups: 202,
  clean_position_share: "0.9731",
  gap_threshold_seconds: 300.0,
  coverage_threshold: "0.5",
};

export const vrmWithCoverage: MetricValue = {
  ...vrmValue,
  metric_value_id: "mv-vrm-2",
  calc_version: "0.2.0",
  detail: vrmCoverageDetail,
};

/** UptDetail shape (upt_v0, handoff 0005) — real sources only. */
export const uptDetail = {
  total_boardings_counted: 41567,
  operated_trips: 9123,
  trips_with_events: 9032,
  missing_trips: 91,
  missing_share: "0.0100",
  factor_applied: "1.010075",
  source_mix: { tides: 41567 },
  missing_trip_threshold: "0.02",
  imbalance_threshold: "0.10",
};

export const uptValue: MetricValue = {
  metric_value_id: "mv-upt-1",
  metric: "upt",
  unit: "unlinked_passenger_trips",
  period_start: "2026-03-01",
  period_end: "2026-03-31",
  scope: "agency",
  value: "41985.90", // trailing zero on purpose: must render verbatim
  calc_name: "upt_v0",
  calc_version: "0.5.0",
  computed_at: "2026-04-01T06:00:00Z",
  certification_status: "uncertified",
  detail: uptDetail,
};

/** Same UPT figure but computed partly from simulator output. */
export const simulatedUptValue: MetricValue = {
  ...uptValue,
  metric_value_id: "mv-upt-sim-1",
  detail: {
    ...uptDetail,
    source_mix: { tides: 40000, tides_simulated: 1567 },
  },
};

/**
 * Demand Response figures (handoff 0013): DR calcs persist under scope
 * `mode:DR` + `mode:DR:tos:<tos>` only — never `agency`. Detail shapes
 * mirror the live dr_* rows (services/calc headway_calc/dr.py); every
 * current DR row is simulator-sourced, so source_mix carries dr_simulated
 * and the SIMULATED badge must appear via the existing plumbing.
 */
export const drVrhModeValue: MetricValue = {
  metric_value_id: "mv-dr-vrh-mode",
  metric: "vrh",
  unit: "hours",
  period_start: "2026-07-14",
  period_end: "2026-07-16",
  scope: "mode:DR",
  value: "24.63",
  calc_name: "dr_vrh_v0",
  calc_version: "0.1.0",
  computed_at: "2026-07-13T07:48:08Z",
  certification_status: "uncertified",
  detail: {
    tos_mix: { DO: 48, PT: 31, TX: 16 },
    source_mix: { dr_simulated: 95 },
    vehicle_days: 12,
    no_show_trips: 9,
    revenue_spans: 31,
    trips_counted: 95,
    vehicle_days_counted: 12,
    vehicle_days_excluded: 0,
  },
};

/** A TX (taxi) vehicle-hours figure: onboard-only + no-deadhead rules. */
export const drVrhTxValue: MetricValue = {
  ...drVrhModeValue,
  metric_value_id: "mv-dr-vrh-tx",
  scope: "mode:DR:tos:TX",
  value: "3.09",
  detail: {
    tos_mix: { TX: 16 },
    source_mix: { dr_simulated: 16 },
    vehicle_days: 2,
    no_show_trips: 2,
    revenue_spans: 9,
    trips_counted: 16,
    vehicle_days_counted: 2,
    vehicle_days_excluded: 0,
  },
};

/** A TN vehicle-miles figure: no-deadhead + no-show rules together. */
export const drVrmTnValue: MetricValue = {
  ...drVrhModeValue,
  metric_value_id: "mv-dr-vrm-tn",
  metric: "vrm",
  unit: "miles",
  scope: "mode:DR:tos:TN",
  value: "42.10",
  calc_name: "dr_vrm_v0",
  detail: {
    tos_mix: { TN: 7 },
    source_mix: { dr_simulated: 7 },
    vehicle_days: 1,
    no_show_trips: 1,
    revenue_spans: 3,
    trips_counted: 7,
  },
};

/** The DR VOMS figure: atypical days INCLUDED (opposite of fleet VOMS). */
export const drVomsModeValue: MetricValue = {
  ...drVrhModeValue,
  metric_value_id: "mv-dr-voms-mode",
  metric: "voms",
  unit: "vehicles",
  value: "6",
  calc_name: "dr_voms_v0",
  detail: {
    tos_mix: { DO: 48, PT: 31, TX: 16 },
    source_mix: { dr_simulated: 95 },
    peak_start: "2026-07-14T13:05:00Z",
    vehicle_days: 12,
    peak_vehicles: 6,
    unique_vehicles: 6,
    includes_atypical_days: true,
  },
};

/** The DR PMT figure — feeds the existing pmt metric under DR scopes. */
export const drPmtModeValue: MetricValue = {
  ...drVrhModeValue,
  metric_value_id: "mv-dr-pmt-mode",
  metric: "pmt",
  unit: "passenger_miles",
  value: "1112.23",
  calc_name: "dr_pmt_v0",
  detail: {
    tos_mix: { DO: 48, PT: 31, TX: 16 },
    source_mix: { dr_simulated: 95 },
    no_show_trips: 9,
    trips_counted: 84,
    persons_counted: 204,
    passenger_miles_counted: "1112.23",
    trips_excluded_missing_distance: 2,
  },
};

/**
 * Operations metrics (handoff 0014): category='ops' rows exactly as the
 * live API serves them (real MBTA figures from the 2026-07-13 ops run —
 * agency OTP 54.10 %, agency cvh 0.3010; detail shapes verbatim from
 * GET /metrics/values?category=ops including the full derive_stop_passages
 * accounting with its three refusal reasons). Never certifiable: the
 * database CHECK makes a certified ops row unrepresentable.
 */

/** The shared derivation accounting every ops figure carries. */
export const opsDerivationDetail = {
  occurrences: 29697,
  trips_observed: 26635,
  derivation_name: "derive_stop_passages",
  passages_derived: 535756,
  stops_considered: 692465,
  derivation_version: "0.1.0",
  stop_radius_meters: 100.0,
  refused_cadence_gap: 3880,
  refused_not_reached: 131384,
  positions_considered: 2268231,
  positions_deduplicated: 276757,
  trips_without_schedule: 4260,
  max_passage_gap_seconds: 120.0,
  min_occurrence_positions: 3,
  occurrence_split_seconds: 10800.0,
  stops_missing_coordinates: 0,
  refused_endpoint_unbounded: 21445,
  occurrences_skipped_few_positions: 1600,
};

export const opsOtpAgencyValue: MetricValue = {
  metric_value_id: "mv-ops-otp-agency",
  metric: "otp",
  unit: "percent",
  period_start: "2026-07-01",
  period_end: "2026-08-01",
  scope: "agency",
  value: "54.10",
  calc_name: "otp_v0",
  calc_version: "0.1.0",
  computed_at: "2026-07-13T16:16:42Z",
  certification_status: "uncertified",
  category: "ops",
  detail: {
    derivation: opsDerivationDetail,
    late_count: 151267,
    early_count: 94663,
    on_time_count: 289826,
    agency_timezone: "America/New_York",
    passages_considered: 535756,
    passages_unscheduled: 0,
    deviation_mean_seconds: "179.66",
    late_tolerance_seconds: 300,
    early_tolerance_seconds: 60,
    deviation_median_seconds: "143.00",
  },
};

/** A route-level OTP row (route:1 = 44.16 in the live run). */
export const opsOtpRouteValue: MetricValue = {
  ...opsOtpAgencyValue,
  metric_value_id: "mv-ops-otp-route-1",
  scope: "route:1",
  value: "44.16",
};

export const opsCvhAgencyValue: MetricValue = {
  metric_value_id: "mv-ops-cvh-agency",
  metric: "headway_adherence",
  unit: "ratio",
  period_start: "2026-07-01",
  period_end: "2026-08-01",
  scope: "agency",
  value: "0.3010",
  calc_name: "headway_adherence_v0",
  calc_version: "0.1.0",
  computed_at: "2026-07-13T16:16:42Z",
  certification_status: "uncertified",
  category: "ops",
  detail: {
    derivation: opsDerivationDetail,
    pairs_counted: 494457,
    stops_covered: 7146,
    routes_covered: 172,
    pairs_excluded_inverted: 20143,
    pairs_excluded_over_cap: 10020,
    stddev_deviation_seconds: "524.52",
    pairs_excluded_unscheduled: 0,
    max_scheduled_headway_seconds: 7200,
    mean_scheduled_headway_seconds: "1742.47",
  },
};

/** A route-level cvh row (route:66 = 0.4476 in the live run). */
export const opsCvhRouteValue: MetricValue = {
  ...opsCvhAgencyValue,
  metric_value_id: "mv-ops-cvh-route-66",
  scope: "route:66",
  value: "0.4476",
};

export const opsValues: MetricValue[] = [
  opsOtpAgencyValue,
  opsOtpRouteValue,
  opsCvhAgencyValue,
  opsCvhRouteValue,
];

/**
 * Provenance tree shaped per LineageNode: transform_name/version describe the
 * transform that PRODUCED the node; raw.records rows are leaves.
 */
export const lineageTree: LineageNode = {
  kind: "computed.metric_values",
  id: "mv-vrm-1",
  transform_name: "vrm_v0",
  transform_version: "0.1.0",
  inputs: [
    {
      kind: "canonical.vehicle_positions",
      id: "vp-100",
      transform_name: "gtfsrt_normalizer",
      transform_version: "0.2.0",
      inputs: [
        {
          kind: "raw.records",
          id: "sha256:aaaa1111",
          transform_name: null,
          transform_version: null,
          inputs: [],
        },
      ],
    },
    {
      kind: "canonical.vehicle_positions",
      id: "vp-101",
      transform_name: "gtfsrt_normalizer",
      transform_version: "0.2.0",
      inputs: [
        {
          kind: "raw.records",
          id: "sha256:bbbb2222",
          transform_name: null,
          transform_version: null,
          inputs: [],
        },
      ],
    },
  ],
};

/**
 * A larger provenance tree (26 raw records) for the lineage GRAPH's collapsed
 * raw tier and its 20-per-page expansion. Same shape as lineageTree: every
 * canonical position produced by gtfsrt_normalizer 0.2.0 from one raw record.
 */
export const lineageTreeLarge: LineageNode = {
  kind: "computed.metric_values",
  id: "mv-vrm-1",
  transform_name: "vrm_v0",
  transform_version: "0.1.0",
  inputs: Array.from({ length: 26 }, (_, i) => ({
    kind: "canonical.vehicle_positions",
    id: `vp-${100 + i}`,
    transform_name: "gtfsrt_normalizer",
    transform_version: "0.2.0",
    inputs: [
      {
        kind: "raw.records",
        id: `sha256:raw${String(i).padStart(4, "0")}`,
        transform_name: null,
        transform_version: null,
        inputs: [],
      },
    ],
  })),
};

/**
 * Dashboard fixtures (handoff 0008 pillar B): a short daily UPT history, two
 * months of VRM/VRH with coverage detail (the detail JSONB history the
 * coverage chart reads), and certified latest figures for the hero tiles.
 * All values are decimal STRINGS with trailing zeros on purpose: the
 * dashboard must render them verbatim.
 */

export const dashboardUptDaily: MetricValue[] = [
  {
    ...uptValue,
    metric_value_id: "mv-upt-d1",
    period_start: "2026-03-01",
    period_end: "2026-03-01",
    value: "1401.00",
    detail: undefined,
  },
  {
    ...uptValue,
    metric_value_id: "mv-upt-d2",
    period_start: "2026-03-02",
    period_end: "2026-03-02",
    value: "1250.50",
    detail: undefined,
  },
  {
    ...uptValue,
    metric_value_id: "mv-upt-d3",
    period_start: "2026-03-03",
    period_end: "2026-03-03",
    value: "1398.25",
    certification_status: "certified",
    // Simulated source: the hero tile must carry the SimulatedBadge.
    detail: { source_mix: { tides: 1000, tides_simulated: 398 } },
  },
];

export const dashboardVrmHistory: MetricValue[] = [
  {
    ...vrmValue,
    metric_value_id: "mv-vrm-feb",
    period_start: "2026-02-01",
    period_end: "2026-02-28",
    value: "11111.10",
    calc_version: "0.2.0",
    certification_status: "certified",
    detail: { ...vrmCoverageDetail, coverage: "0.9126" },
  },
  {
    ...vrmValue,
    metric_value_id: "mv-vrm-mar",
    period_start: "2026-03-01",
    period_end: "2026-03-31",
    value: "12345.60",
    calc_version: "0.2.0",
    detail: { ...vrmCoverageDetail, coverage: "0.8850" },
  },
];

export const dashboardVrhHistory: MetricValue[] = [
  {
    ...vrhValue,
    metric_value_id: "mv-vrh-feb",
    period_start: "2026-02-01",
    period_end: "2026-02-28",
    value: "987.25",
    calc_version: "0.2.0",
    certification_status: "certified",
    detail: { ...vrmCoverageDetail, coverage: "0.9500" },
  },
  {
    ...vrhValue,
    metric_value_id: "mv-vrh-mar",
    period_start: "2026-03-01",
    period_end: "2026-03-31",
    value: "1002.75",
    calc_version: "0.2.0",
    detail: { ...vrmCoverageDetail, coverage: "0.9033" },
  },
];

export const dashboardValues: MetricValue[] = [
  ...dashboardUptDaily,
  ...dashboardVrmHistory,
  ...dashboardVrhHistory,
];

export const blockingIssue: DqIssue = {
  issue_id: "dq-1",
  issue_type: "telemetry_gap",
  severity: "blocking",
  status: "open",
  owner: null,
  title: "Bus 1207 sent no location data for 42 minutes on March 3",
  description:
    "Headway received no position reports from Bus 1207 between 9:12 and 9:54 on March 3, so the miles for that window are unknown.",
  source_record_ids: ["sha256:aaaa1111"],
  created_at: "2026-03-04T02:00:00Z",
  resolved_at: null,
  resolution: null,
  resolution_minutes: null,
};

export const warningIssue: DqIssue = {
  issue_id: "dq-2",
  issue_type: "source_conflict",
  severity: "warning",
  status: "owned",
  owner: "maria.ops",
  title: "GPS miles and odometer miles disagree for Bus 1103 on March 5",
  description:
    "GPS-based miles and the odometer reading for Bus 1103 on March 5 differ by 41 miles. Choose which source to trust and note why.",
  source_record_ids: ["sha256:cccc3333", "sha256:dddd4444"],
  created_at: "2026-03-06T02:00:00Z",
  resolved_at: null,
  resolution: null,
  resolution_minutes: null,
};

export const resolvedIssue: DqIssue = {
  issue_id: "dq-3",
  issue_type: "schema_drift",
  severity: "info",
  status: "resolved",
  owner: "sam.data",
  title: "The March 1 GTFS feed added a new optional field",
  description:
    "The agency's GTFS feed added an optional field Headway did not recognize. No figures were affected.",
  source_record_ids: null,
  created_at: "2026-03-01T12:00:00Z",
  resolved_at: "2026-03-02T09:00:00Z",
  resolution: "Confirmed the new field is informational only; mapping updated.",
  // Effort metadata (docket #3): 90 minutes -> "≈1.5 hours" in the header.
  resolution_minutes: 90,
};

/**
 * The MR-20 package (docket #2) exactly as GET /reports/mr20 would serve it:
 * reportable:false with its banner and citation, fleet + per-mode cells with
 * value strings VERBATIM (trailing zeros on purpose), a null rail UPT cell
 * with a plain-language reason, and the pending_d2 flag on rail cells.
 */
export const mr20Package: Mr20Package = {
  form: "MR-20",
  month: "2026-03",
  period_start: "2026-03-01",
  period_end: "2026-03-31",
  citation:
    "49 U.S.C. 5335; NTD Monthly Module Reporting Manual, form MR-20 (Monthly Ridership).",
  reportable: false,
  banner:
    "Not reportable: this MR-20 package is assembled from Headway's computed figures for preview only. It has not been verified against FTA's reporting system documentation and must not be submitted.",
  caveats: [
    "VOMS is derived from scheduled maximum service, not observed pull-outs.",
    "Rail figures are on hold until the D-2 form definition is verified.",
  ],
  fleet: {
    upt: {
      value: "41985.90",
      unit: "unlinked_passenger_trips",
      metric_value_id: "mv-upt-1",
      calc_name: "upt_v0",
      calc_version: "0.5.0",
      certification_status: "uncertified",
      flags: [],
      coverage: "0.9902",
    },
    vrm: {
      value: "12345.60",
      unit: "miles",
      metric_value_id: "mv-vrm-1",
      calc_name: "vrm_v0",
      calc_version: "0.2.0",
      certification_status: "certified",
      flags: [],
      coverage: "0.9126",
    },
    vrh: {
      value: "987.25",
      unit: "hours",
      metric_value_id: "mv-vrh-1",
      calc_name: "vrh_v0",
      calc_version: "0.2.0",
      certification_status: "uncertified",
      flags: [],
    },
    voms: {
      value: "38",
      unit: "vehicles",
      metric_value_id: "mv-voms-1",
      calc_name: "voms_v0",
      calc_version: "0.1.0",
      certification_status: "uncertified",
      flags: [],
    },
  },
  modes: {
    MB: {
      upt: {
        value: "40100.50",
        unit: "unlinked_passenger_trips",
        metric_value_id: "mv-upt-mb",
        calc_name: "upt_v0",
        calc_version: "0.5.0",
        certification_status: "uncertified",
        flags: [],
      },
      vrm: {
        value: "11145.60",
        unit: "miles",
        metric_value_id: "mv-vrm-mb",
        calc_name: "vrm_v0",
        calc_version: "0.2.0",
        certification_status: "certified",
        flags: [],
      },
      vrh: {
        value: "900.00",
        unit: "hours",
        metric_value_id: "mv-vrh-mb",
        calc_name: "vrh_v0",
        calc_version: "0.2.0",
        certification_status: "uncertified",
        flags: [],
      },
      voms: {
        value: "35",
        unit: "vehicles",
        metric_value_id: "mv-voms-mb",
        calc_name: "voms_v0",
        calc_version: "0.1.0",
        certification_status: "uncertified",
        flags: [],
      },
    },
    HR: {
      upt: {
        value: null,
        unit: "unlinked_passenger_trips",
        metric_value_id: null,
        calc_name: null,
        calc_version: null,
        certification_status: null,
        flags: ["pending_d2"],
        reason:
          "Rail passenger counts are on hold until the D-2 form definition is verified.",
      },
      vrm: {
        value: "1200.00",
        unit: "miles",
        metric_value_id: "mv-vrm-hr",
        calc_name: "vrm_v0",
        calc_version: "0.2.0",
        certification_status: "uncertified",
        flags: ["pending_d2"],
      },
      vrh: {
        value: "87.25",
        unit: "hours",
        metric_value_id: "mv-vrh-hr",
        calc_name: "vrh_v0",
        calc_version: "0.2.0",
        certification_status: "uncertified",
        flags: ["pending_d2"],
      },
      voms: {
        value: "3",
        unit: "vehicles",
        metric_value_id: "mv-voms-hr",
        calc_name: "voms_v0",
        calc_version: "0.1.0",
        certification_status: "uncertified",
        flags: ["pending_d2"],
      },
    },
  },
};
/**
 * Safety & Security fixtures (handoff 0010), typed against
 * services/api routers/safety.py's response models exactly.
 * property_damage_usd is a decimal STRING with trailing zeros on purpose:
 * the UI must render it verbatim, never parse it. Classifications are what
 * the deterministic sscls_v0 classifier returns — fixtures here are display
 * material, never a classification the UI computed.
 */

/** GET /safety/events record: a bus collision that met the injury threshold. */
export const safetyMajorEvent: SafetyEventRecord = {
  event_id: "ev-major-1",
  occurred_at: "2026-07-02T14:30:00Z",
  mode: "bus",
  type_of_service: "DO",
  event_category: "collision",
  narrative:
    "A bus collided with a car at Elm St and 5th Ave; two passengers were taken to the hospital by ambulance.",
  location: "Elm St & 5th Ave",
  fatalities: 0,
  injuries: 2,
  property_damage_usd: "18000.00",
  serious_injury: false,
  substantial_damage: false,
  towed: true,
  evacuation_life_safety: false,
  assault_on_worker: false,
  involves_transit_vehicle: true,
  involves_second_rail_vehicle: false,
  grade_crossing: false,
  runaway_train: false,
  evacuation_to_rail_row: false,
  entered_by: "maria.ops",
  entered_at: "2026-07-02T18:00:00Z",
  superseded_by: null,
  classification: "major",
  thresholds_met: ["injury_immediate_transport"],
  classifier_version: "sscls_v0 0.1.1",
  classified_at: "2026-07-02T18:00:01Z",
};

/** A non-major assault on a worker (no injury — still S&S-50 scope).
 *  Structural rule (migration 0017 CHECK): 'major' ⇔ thresholds_met
 *  non-empty, so a non-major record carries an empty thresholds_met. */
export const safetyNonMajorEvent: SafetyEventRecord = {
  event_id: "ev-nonmajor-1",
  occurred_at: "2026-06-14T09:10:00Z",
  mode: "bus",
  type_of_service: "DO",
  event_category: "assault",
  narrative:
    "A passenger spat on the bus operator at the Downtown Transit Center. The operator was not injured.",
  location: "Downtown Transit Center",
  fatalities: 0,
  injuries: 0,
  property_damage_usd: null,
  serious_injury: false,
  substantial_damage: false,
  towed: false,
  evacuation_life_safety: false,
  assault_on_worker: true,
  involves_transit_vehicle: true,
  involves_second_rail_vehicle: false,
  grade_crossing: false,
  runaway_train: false,
  evacuation_to_rail_row: false,
  entered_by: "maria.ops",
  entered_at: "2026-06-14T12:00:00Z",
  superseded_by: null,
  classification: "non_major",
  thresholds_met: [],
  classifier_version: "sscls_v0 0.1.1",
  classified_at: "2026-06-14T12:00:01Z",
};

export const safetyNotReportableEvent: SafetyEventRecord = {
  event_id: "ev-notrep-1",
  occurred_at: "2026-06-20T16:45:00Z",
  mode: "bus",
  type_of_service: "DO",
  event_category: "other",
  narrative:
    "A bus mirror clipped a parked car's mirror while pulling into a stop. No one was hurt and both vehicles stayed in service.",
  location: "Main St stop 14",
  fatalities: 0,
  injuries: 0,
  property_damage_usd: "350.00",
  serious_injury: false,
  substantial_damage: false,
  towed: false,
  evacuation_life_safety: false,
  assault_on_worker: false,
  involves_transit_vehicle: true,
  involves_second_rail_vehicle: false,
  grade_crossing: false,
  runaway_train: false,
  evacuation_to_rail_row: false,
  entered_by: "sam.data",
  entered_at: "2026-06-20T17:30:00Z",
  superseded_by: null,
  classification: "not_reportable",
  thresholds_met: [],
  classifier_version: "sscls_v0 0.1.1",
  classified_at: "2026-06-20T17:30:01Z",
};

/** The rich verdict POST /safety/events returns for safetyMajorEvent. */
export const safetyMajorResult: SafetyClassificationResult = {
  classification: "major",
  thresholds_met: ["injury_immediate_transport"],
  explanations: [
    {
      threshold: "injury_immediate_transport",
      plain_language:
        "2 person(s) were taken directly from the scene for medical care.",
      citation:
        "Exhibit 5, p. 16 — 'Immediate transport away from the scene for medical attention for one or more persons.' (services/calc/REGULATORY_TRACKER.md, verified 2026-07-12)",
    },
  ],
  non_major_basis: [],
  effective_category: "collision",
  is_rail_mode: false,
  summary:
    "This event meets 1 major-event threshold(s) and is ONE reportable major event (an event meeting one or more thresholds is one report — p. 14): an S&S-40 Major Event Report is due no later than 30 days after the date of the event (Exhibit 2, p. 4).",
  classifier_version: "sscls_v0 0.1.1",
};

export const safetyMajorCreated: SafetyEventCreated = {
  event_id: safetyMajorEvent.event_id,
  entered_at: safetyMajorEvent.entered_at,
  result: safetyMajorResult,
  audit_event_id: 41,
};

/** The verdict for a non-major assault: S&S-50 scope via non_major_basis. */
export const safetyAssaultCreated: SafetyEventCreated = {
  event_id: safetyNonMajorEvent.event_id,
  entered_at: safetyNonMajorEvent.entered_at,
  result: {
    classification: "non_major",
    thresholds_met: [],
    explanations: [],
    non_major_basis: [
      {
        threshold: "non_major_assault_on_worker",
        plain_language:
          "A transit worker was assaulted; no injury is required for this to belong on the S&S-50.",
        citation:
          "p. 3 — 'Assaults on a transit worker do not require an injury to be reportable on the S&S-50.' (services/calc/REGULATORY_TRACKER.md, verified 2026-07-12)",
      },
    ],
    effective_category: "assault",
    is_rail_mode: false,
    summary:
      "This event meets no major-event threshold but belongs on the S&S-50 Non-Major Monthly Summary for its month, mode, and type of service (p. 3).",
    classifier_version: "sscls_v0 0.1.1",
  },
  audit_event_id: 42,
};

/**
 * A correction pair: the ORIGINAL record (superseded, never deleted) and
 * the correcting record it points at, plus the supersede response. The UI
 * must keep the original visible — struck and linked — because hiding it
 * would break the audit story.
 */
export const safetyCorrectionEvent: SafetyEventRecord = {
  ...safetyMajorEvent,
  event_id: "ev-correction-1",
  injuries: 1,
  narrative:
    "Correction: one passenger was taken to the hospital by ambulance; the second declined care at the scene.",
  entered_at: "2026-07-03T09:00:00Z",
  superseded_by: null,
  classified_at: "2026-07-03T09:00:01Z",
};

export const safetySupersededEvent: SafetyEventRecord = {
  ...safetyMajorEvent,
  superseded_by: safetyCorrectionEvent.event_id,
};

export const safetySupersededResponse: SafetyEventSuperseded = {
  original_event_id: safetyMajorEvent.event_id,
  replacement_event_id: safetyCorrectionEvent.event_id,
  entered_at: safetyCorrectionEvent.entered_at,
  result: {
    ...safetyMajorResult,
    explanations: [
      {
        threshold: "injury_immediate_transport",
        plain_language:
          "1 person(s) were taken directly from the scene for medical care.",
        citation:
          "Exhibit 5, p. 16 — 'Immediate transport away from the scene for medical attention for one or more persons.' (services/calc/REGULATORY_TRACKER.md, verified 2026-07-12)",
      },
    ],
  },
  audit_event_id: 43,
};


// ---- sampling (handoff 0012) ----
//
// Mocks typed against services/api routers/sampling.py exactly. Every
// regulatory string below (citations, guidance, method labels, caveats,
// the retention note) is the REAL sampling_v0 / router text, extracted
// programmatically from the live modules when these fixtures were
// generated — and every figure (required sizes, drawn units, estimate)
// is the calc's own output for these inputs, never a hand-made number.

/** GET /sampling/options — the calc selector's vocabulary, verbatim. */
export const samplingOptions: SamplingOptions = {
  "modes": {
    "DR": "demand response (DR)",
    "VP": "commuter vanpool (VP)",
    "MB": "bus (MB and TB)",
    "TB": "bus (MB and TB)",
    "CR": "commuter rail (CR)",
    "LR": "other rail modes (LR, HR, MR, AG)",
    "HR": "other rail modes (LR, HR, MR, AG)",
    "MR": "other rail modes (LR, HR, MR, AG)",
    "AG": "other rail modes (LR, HR, MR, AG)"
  },
  "units_by_mode": {
    "DR": [
      "vehicle_days"
    ],
    "VP": [
      "vehicle_days"
    ],
    "MB": [
      "one_way_trips",
      "round_trips"
    ],
    "TB": [
      "one_way_trips",
      "round_trips"
    ],
    "CR": [
      "one_way_car_trips"
    ],
    "LR": [
      "one_way_car_trips",
      "one_way_train_trips"
    ],
    "HR": [
      "one_way_car_trips",
      "one_way_train_trips"
    ],
    "MR": [
      "one_way_car_trips",
      "one_way_train_trips"
    ],
    "AG": [
      "one_way_car_trips",
      "one_way_train_trips"
    ]
  },
  "efficiency_options": [
    "aptl",
    "aptl_grouped",
    "base"
  ],
  "creatable_options": [
    "aptl",
    "base"
  ],
  "frequencies": [
    "quarterly",
    "monthly",
    "weekly"
  ],
  "service_day_types": [
    "Weekday",
    "Saturday",
    "Sunday"
  ],
  "eligibility_guidance": [
    "Ready-to-use sampling plans may be used only under the §41.01 conditions — (a) New Mode: 'If you will be sampling and reporting for the first time this current report year for a particular mode that you do not already operate'; (b) New Type of Service: 'If you will be sampling and reporting this current report year for a particular type of service for the first time'; or (c) No Sample Data: 'If you have reported your service to the NTD before through random sampling, but no longer have the original raw sample data.' Headway records your plan; whether your agency meets one of these conditions is your determination. (FTA NTD Sampling Manual, March 31, 2009 (verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — NTD Sampling Manual' / 'Sampling plan tables — implementation quotes'), §41.01, p. 3)",
    "Reuse next year: 'You should not use it again if your next report year is your mandatory sampling year. After you have collected the sample data from this year, you should develop a template sampling plan with that sample data for your next report year.' You may reuse it only if next year is not a mandatory sampling year (§41.03(b)). Template plans (Section 50) are not yet mechanized in Headway. (FTA NTD Sampling Manual, March 31, 2009 (verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — NTD Sampling Manual' / 'Sampling plan tables — implementation quotes'), §41.03, p. 3)",
    "The estimate this plan supports must meet FTA's floor: 'Minimum confidence of 95 percent; and Minimum precision level of ±10 percent' — met by following the plan exactly: 'If a transit agency samples, they must follow the sampling technique exactly.' (2026 NTD Policy Manual, Full Reporting, p. 149 — verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — Passenger Miles Traveled')"
  ],
  "retention_note": "Keep every sampling record — the plan, the recorded seed, the drawn service-unit lists, and each unit's observed UPT and PMT — for at least 3 years (2026 NTD Policy Manual, Full Reporting, p. 150; verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — Passenger Miles Traveled'). Headway keeps them indefinitely: sampling records are append-only and are corrected by superseding, never by editing."
};

/** A freshly created bus plan (no draw yet — status 'created'). */
export const samplingPlanMb: SamplingPlanRecord = {
  "plan_id": "plan-mb-1",
  "report_year": 2026,
  "mode": "MB",
  "type_of_service": "DO",
  "unit": "one_way_trips",
  "efficiency_option": "aptl",
  "frequency": "monthly",
  "required_per_period": 27,
  "required_annual": 324,
  "table_citation": "Table 43.03. Ready-to-Use Sampling Plans for Bus (MB and TB) Services (p. 5), 'Reporting 100% UPT (APTL Option) — Without Route Grouping, column (2)': One-way trips for a Month = 27; Total Sample Size for Year = 324. (FTA NTD Sampling Manual, March 31, 2009 (verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — NTD Sampling Manual' / 'Sampling plan tables — implementation quotes'))",
  "selector_version": "sampling_v0 0.1.0",
  "status": "created",
  "created_by": "dsteward",
  "created_at": "2026-07-12T10:00:00Z"
};

export const samplingPlanMbCreated: SamplingPlanCreated = {
  plan: samplingPlanMb,
  guidance: [
    "Ready-to-use sampling plans may be used only under the §41.01 conditions — (a) New Mode: 'If you will be sampling and reporting for the first time this current report year for a particular mode that you do not already operate'; (b) New Type of Service: 'If you will be sampling and reporting this current report year for a particular type of service for the first time'; or (c) No Sample Data: 'If you have reported your service to the NTD before through random sampling, but no longer have the original raw sample data.' Headway records your plan; whether your agency meets one of these conditions is your determination. (FTA NTD Sampling Manual, March 31, 2009 (verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — NTD Sampling Manual' / 'Sampling plan tables — implementation quotes'), §41.01, p. 3)",
    "Reuse next year: 'You should not use it again if your next report year is your mandatory sampling year. After you have collected the sample data from this year, you should develop a template sampling plan with that sample data for your next report year.' You may reuse it only if next year is not a mandatory sampling year (§41.03(b)). Template plans (Section 50) are not yet mechanized in Headway. (FTA NTD Sampling Manual, March 31, 2009 (verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — NTD Sampling Manual' / 'Sampling plan tables — implementation quotes'), §41.03, p. 3)",
    "The estimate this plan supports must meet FTA's floor: 'Minimum confidence of 95 percent; and Minimum precision level of ±10 percent' — met by following the plan exactly: 'If a transit agency samples, they must follow the sampling technique exactly.' (2026 NTD Policy Manual, Full Reporting, p. 149 — verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — Passenger Miles Traveled')"
  ],
  retention_note: "Keep every sampling record — the plan, the recorded seed, the drawn service-unit lists, and each unit's observed UPT and PMT — for at least 3 years (2026 NTD Policy Manual, Full Reporting, p. 150; verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — Passenger Miles Traveled'). Headway keeps them indefinitely: sampling records are append-only and are corrected by superseding, never by editing.",
  audit_event_id: 71,
};

/** An active commuter-rail plan: 4 quarterly draws of 8 on file. */
export const samplingPlanCr: SamplingPlanRecord = {
  "plan_id": "plan-cr-1",
  "report_year": 2026,
  "mode": "CR",
  "type_of_service": "DO",
  "unit": "one_way_car_trips",
  "efficiency_option": "aptl",
  "frequency": "quarterly",
  "required_per_period": 8,
  "required_annual": 32,
  "table_citation": "Table 43.05. Ready-to-Use Sampling Plans for Commuter Rail (CR) (p. 6), 'Reporting 100% UPT (APTL Option)': One-way car trips for a Quarter = 8; Total Sample Size for Year = 32. (FTA NTD Sampling Manual, March 31, 2009 (verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — NTD Sampling Manual' / 'Sampling plan tables — implementation quotes'))",
  "selector_version": "sampling_v0 0.1.0",
  "status": "active",
  "created_by": "dsteward",
  "created_at": "2026-01-05T08:00:00Z"
};

/** The four quarterly draws — selected units are the REAL calc drawer's
 *  output for these frames and seeds (reproducible forever). */
export const samplingDrawsCr: SamplingDrawRecord[] = [
  {
    "draw_id": "draw-cr-1",
    "plan_id": "plan-cr-1",
    "period_label": "2026-Q1",
    "frame_size": 20,
    "selected_units": [
      "2026-Q1/car-trip-14",
      "2026-Q1/car-trip-07",
      "2026-Q1/car-trip-12",
      "2026-Q1/car-trip-16",
      "2026-Q1/car-trip-19",
      "2026-Q1/car-trip-10",
      "2026-Q1/car-trip-01",
      "2026-Q1/car-trip-20"
    ],
    "seed": "headway-cr-2026-q1",
    "required_per_period": 8,
    "oversample_units": 0,
    "drawer_version": "sampling_v0 0.1.0",
    "drawn_by": "dsteward",
    "drawn_at": "2026-01-02T09:00:00Z"
  },
  {
    "draw_id": "draw-cr-2",
    "plan_id": "plan-cr-1",
    "period_label": "2026-Q2",
    "frame_size": 20,
    "selected_units": [
      "2026-Q2/car-trip-20",
      "2026-Q2/car-trip-14",
      "2026-Q2/car-trip-19",
      "2026-Q2/car-trip-07",
      "2026-Q2/car-trip-03",
      "2026-Q2/car-trip-10",
      "2026-Q2/car-trip-16",
      "2026-Q2/car-trip-01"
    ],
    "seed": "headway-cr-2026-q2",
    "required_per_period": 8,
    "oversample_units": 0,
    "drawer_version": "sampling_v0 0.1.0",
    "drawn_by": "dsteward",
    "drawn_at": "2026-04-02T09:00:00Z"
  },
  {
    "draw_id": "draw-cr-3",
    "plan_id": "plan-cr-1",
    "period_label": "2026-Q3",
    "frame_size": 20,
    "selected_units": [
      "2026-Q3/car-trip-01",
      "2026-Q3/car-trip-08",
      "2026-Q3/car-trip-17",
      "2026-Q3/car-trip-20",
      "2026-Q3/car-trip-15",
      "2026-Q3/car-trip-10",
      "2026-Q3/car-trip-18",
      "2026-Q3/car-trip-14"
    ],
    "seed": "headway-cr-2026-q3",
    "required_per_period": 8,
    "oversample_units": 0,
    "drawer_version": "sampling_v0 0.1.0",
    "drawn_by": "dsteward",
    "drawn_at": "2026-07-02T09:00:00Z"
  },
  {
    "draw_id": "draw-cr-4",
    "plan_id": "plan-cr-1",
    "period_label": "2026-Q4",
    "frame_size": 20,
    "selected_units": [
      "2026-Q4/car-trip-02",
      "2026-Q4/car-trip-20",
      "2026-Q4/car-trip-18",
      "2026-Q4/car-trip-19",
      "2026-Q4/car-trip-04",
      "2026-Q4/car-trip-05",
      "2026-Q4/car-trip-11",
      "2026-Q4/car-trip-01"
    ],
    "seed": "headway-cr-2026-q4",
    "required_per_period": 8,
    "oversample_units": 0,
    "drawer_version": "sampling_v0 0.1.0",
    "drawn_by": "dsteward",
    "drawn_at": "2026-010-02T09:00:00Z"
  }
];

/** POST …/draws 201 response for the first quarter (method = the calc's
 *  documented §63.03 procedure, verbatim). */
export const samplingDrawCreatedQ1: SamplingDrawCreated = {
  draw: samplingDrawsCr[0],
  method: "Keyed-hash random ordering (a §63.03(b) 'any other method'): each service unit in the provided list is keyed by SHA-256 of the recorded seed and the unit id; the list is ordered by key and the first n units are selected. With a seed produced by a cryptographic randomness source (recorded on the plan for audit), the ordering is random — §63.03(b)(1); each unit appears exactly once in the ordering and duplicate unit ids are refused, so no unit can be selected more than once — without replacement, §63.03(b)(2) ('Without replacement means that the method will not select the same service unit more than once.'). Given the same seed and the same unit list the draw reproduces exactly. (FTA NTD Sampling Manual, March 31, 2009 (verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — NTD Sampling Manual' / 'Sampling plan tables — implementation quotes'), §63.03, p. 19)",
  oversampling_note: null,
  retention_note: "Keep every sampling record — the plan, the recorded seed, the drawn service-unit lists, and each unit's observed UPT and PMT — for at least 3 years (2026 NTD Policy Manual, Full Reporting, p. 150; verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — Passenger Miles Traveled'). Headway keeps them indefinitely: sampling records are append-only and are corrected by superseding, never by editing.",
  audit_event_id: 72,
};

/** 31 of the 32 drawn units measured (the last drawn unit is pending). */
export const samplingMeasurementsCr: SamplingMeasurementRecord[] = [
  {
    "measurement_id": "meas-01",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q1/car-trip-14",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-02",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q1/car-trip-07",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-03",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q1/car-trip-12",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-04",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q1/car-trip-16",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-05",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q1/car-trip-19",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-06",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q1/car-trip-10",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-07",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q1/car-trip-01",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-08",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q1/car-trip-20",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-09",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q2/car-trip-20",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-10",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q2/car-trip-14",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-11",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q2/car-trip-19",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-12",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q2/car-trip-07",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-13",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q2/car-trip-03",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-14",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q2/car-trip-10",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-15",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q2/car-trip-16",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-16",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q2/car-trip-01",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-17",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q3/car-trip-01",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-18",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q3/car-trip-08",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-19",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q3/car-trip-17",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-20",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q3/car-trip-20",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-21",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q3/car-trip-15",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-22",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q3/car-trip-10",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-23",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q3/car-trip-18",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-24",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q3/car-trip-14",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-25",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q4/car-trip-02",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-26",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q4/car-trip-20",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-27",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q4/car-trip-18",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-28",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q4/car-trip-19",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-29",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q4/car-trip-04",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-30",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q4/car-trip-05",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  },
  {
    "measurement_id": "meas-31",
    "plan_id": "plan-cr-1",
    "unit_id": "2026-Q4/car-trip-11",
    "observed_upt": 25,
    "observed_pmt": "112.40",
    "service_day_type": null,
    "service_date": null,
    "data_source": "manual_ride_check",
    "notes": null,
    "entered_by": "checker",
    "entered_at": "2026-07-10T09:00:00Z",
    "superseded_by": null
  }
];

/** The final unit's observation (recorded by the measurement test). */
export const samplingFinalMeasurement: SamplingMeasurementRecord = {
  "measurement_id": "meas-32",
  "plan_id": "plan-cr-1",
  "unit_id": "2026-Q4/car-trip-01",
  "observed_upt": 30,
  "observed_pmt": "141.00",
  "service_day_type": null,
  "service_date": null,
  "data_source": "manual_ride_check",
  "notes": null,
  "entered_by": "preparer",
  "entered_at": "2026-07-12T09:00:00Z",
  "superseded_by": null
};

/** GET …/progress — one unit short of the required 32 (undersampled). */
export const samplingProgressUnder: SamplingPlanProgress = {
  "plan": samplingPlanCr,
  "required_per_period": 8,
  "required_annual": 32,
  "draws": [
    {
      "period_label": "2026-Q1",
      "selected": 8,
      "measured": 8,
      "oversample_units": 0
    },
    {
      "period_label": "2026-Q2",
      "selected": 8,
      "measured": 8,
      "oversample_units": 0
    },
    {
      "period_label": "2026-Q3",
      "selected": 8,
      "measured": 8,
      "oversample_units": 0
    },
    {
      "period_label": "2026-Q4",
      "selected": 8,
      "measured": 7,
      "oversample_units": 0
    }
  ],
  "units_selected": 32,
  "units_measured": 31,
  "units_unmeasured": [
    "2026-Q4/car-trip-01"
  ],
  "undersampled": true,
  "undersampling_citation": "An estimate from fewer units than the plan requires does not follow the FTA-approved technique: 'If a transit agency samples, they must follow the sampling technique exactly.' and the estimate must meet 'Minimum confidence of 95 percent; and Minimum precision level of ±10 percent' (2026 NTD Policy Manual, Full Reporting, p. 149 — verified 2026-07-12, REGULATORY_TRACKER.md, 'Verified — Passenger Miles Traveled').",
  "oversampling_citation": "Sampling more units than required is allowed only when the extra units are selected randomly (2026 NTD Policy Manual, Full Reporting, p. 149 — verified 2026-07-12). Headway's drawer extends the same seeded random order, so oversampled units are random by construction and are flagged on the draw record.",
  "retention_note": "Keep every sampling record — the plan, the recorded seed, the drawn service-unit lists, and each unit's observed UPT and PMT — for at least 3 years (2026 NTD Policy Manual, Full Reporting, p. 150; verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — Passenger Miles Traveled'). Headway keeps them indefinitely: sampling records are append-only and are corrected by superseding, never by editing."
};

/** GET …/progress — target met. */
export const samplingProgressComplete: SamplingPlanProgress = {
  "plan": samplingPlanCr,
  "required_per_period": 8,
  "required_annual": 32,
  "draws": [
    {
      "period_label": "2026-Q1",
      "selected": 8,
      "measured": 8,
      "oversample_units": 0
    },
    {
      "period_label": "2026-Q2",
      "selected": 8,
      "measured": 8,
      "oversample_units": 0
    },
    {
      "period_label": "2026-Q3",
      "selected": 8,
      "measured": 8,
      "oversample_units": 0
    },
    {
      "period_label": "2026-Q4",
      "selected": 8,
      "measured": 8,
      "oversample_units": 0
    }
  ],
  "units_selected": 32,
  "units_measured": 32,
  "units_unmeasured": [],
  "undersampled": false,
  "undersampling_citation": "An estimate from fewer units than the plan requires does not follow the FTA-approved technique: 'If a transit agency samples, they must follow the sampling technique exactly.' and the estimate must meet 'Minimum confidence of 95 percent; and Minimum precision level of ±10 percent' (2026 NTD Policy Manual, Full Reporting, p. 149 — verified 2026-07-12, REGULATORY_TRACKER.md, 'Verified — Passenger Miles Traveled').",
  "oversampling_citation": "Sampling more units than required is allowed only when the extra units are selected randomly (2026 NTD Policy Manual, Full Reporting, p. 149 — verified 2026-07-12). Headway's drawer extends the same seeded random order, so oversampled units are random by construction and are flagged on the draw record.",
  "retention_note": "Keep every sampling record — the plan, the recorded seed, the drawn service-unit lists, and each unit's observed UPT and PMT — for at least 3 years (2026 NTD Policy Manual, Full Reporting, p. 150; verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — Passenger Miles Traveled'). Headway keeps them indefinitely: sampling records are append-only and are corrected by superseding, never by editing."
};

/**
 * POST …/estimate response: the estimate block is the REAL sampling_v0
 * output for these 32 observations and a 12,750,000 expansion factor
 * (ratio of totals, §83.05(a); quantization the calc's). Deliberately
 * carries NO metric_value_id — a sampled estimate is never persisted
 * among computed figures.
 */
export const samplingEstimate: SamplingEstimateResponse = {
  "plan_id": "plan-cr-1",
  "estimate": {
    "scope": "annual",
    "sample_size": 32,
    "sample_total_upt": 805,
    "sample_total_pmt": "3625.40",
    "sample_aptl": "4.50",
    "expansion_factor_upt": "12750000",
    "estimated_pmt": "57375000",
    "method": "estimated — sampled average passenger trip length (APTL) method (FTA NTD Sampling Manual, March 31, 2009, Subsection 83): sample APTL = sample total PMT ÷ sample total UPT (§83.05(a) ratio of totals); estimated PMT = 100% UPT expansion factor × sample APTL (§83.01(a), §83.07). Sample observations are manually entered ride-check data; this figure is a sampled ESTIMATE, not a computed PMT measurement."
  },
  "by_service_day": null,
  "units_measured": 32,
  "required_annual": 32,
  "oversampled_by": 0,
  "caveats": [
    "This figure is a SAMPLED ESTIMATE produced by the §83 APTL method. It is not, and is never stored as, a computed PMT measurement (computed.metric_values is untouched by this endpoint).",
    "Sample observations are MANUALLY ENTERED ride-check data: Headway records who entered each observation and when, but cannot verify the on-board counts themselves. Corrections supersede — originals are never edited.",
    "The 100% UPT expansion factor is supplied by the caller and must be the agency's actual 100% count of UPT (§83.01(a): 'You must use your 100% count of UPT as the expansion factor.'). Headway does not verify it against computed UPT figures in v0 — cross-check it against your certified UPT before using this estimate in a submission.",
    "Sampling more units than required is allowed only when the extra units are selected randomly (2026 NTD Policy Manual, Full Reporting, p. 149 — verified 2026-07-12). Headway's drawer extends the same seeded random order, so oversampled units are random by construction and are flagged on the draw record."
  ],
  "citations": [
    "Sample APTL: 'You must determine the sample APTL for a given sample as the ratio of sample total PMT over sample total UPT' — and never the banned average: 'You must not determine the sample APTL as the average of the APTL across individual service units in the sample.' (FTA NTD Sampling Manual, 2009, §83.05(a)/(b), p. 42).",
    "Expansion: 'You must use your 100% count of UPT as the expansion factor.' (§83.01(a), p. 42); annual total PMT per §83.07(a), p. 43.",
    "Table 43.05. Ready-to-Use Sampling Plans for Commuter Rail (CR) (p. 6), 'Reporting 100% UPT (APTL Option)': One-way car trips for a Quarter = 8; Total Sample Size for Year = 32. (FTA NTD Sampling Manual, March 31, 2009 (verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — NTD Sampling Manual' / 'Sampling plan tables — implementation quotes'))"
  ],
  "retention_note": "Keep every sampling record — the plan, the recorded seed, the drawn service-unit lists, and each unit's observed UPT and PMT — for at least 3 years (2026 NTD Policy Manual, Full Reporting, p. 150; verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — Passenger Miles Traveled'). Headway keeps them indefinitely: sampling records are append-only and are corrected by superseding, never by editing.",
  "audit_event_id": 73
};
