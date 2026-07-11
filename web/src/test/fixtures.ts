import type {
  DqIssue,
  LineageNode,
  MetricValue,
  Mr20Package,
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
