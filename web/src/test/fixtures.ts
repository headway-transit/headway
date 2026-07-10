import type { DqIssue, LineageNode, MetricValue } from "../api/types";

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
};
