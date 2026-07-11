# Anomaly-Detector Threshold Tracker — headway-ai

The durable memory mapping every anomaly detector (and version) to its
thresholds and their provenance, in the style of
`services/calc/REGULATORY_TRACKER.md`. **Rule: no detector ships without a
row here, and no threshold that touches reporting may rest on model
judgment** — every threshold is an explicit, deterministic input recorded in
the run report. Anomaly flags are severity `info`/`warning` ONLY and never
block anything; they exist for a human to review. Changing detector logic or
a default mints a new row; shipped rows are never rewritten.

| detector | issue_type | threshold (default) | status / provenance | next increment |
|---|---|---|---|---|
| period-over-period swing (`headway_ai.anomaly.detect_metric_swings`, v1) | `anomaly_metric_swing` | `swing_threshold = 0.25` (Decimal; flags when \|Δ\| strictly > threshold × \|previous\|, stated without division so exactly-at-threshold is exact) | **ENGINEERING DEFAULT** — not an FTA number, not a statistical baseline. Chosen as a conservative first-flag level for the walking-skeleton metric history (only a handful of computed periods exist). Explicit Decimal input, recorded in every AnomalyRunReport; CLI-overridable (`--swing-threshold`). | Statistical baselines per the role file (robust z-scores / median-absolute-deviation, seasonal decomposition) once **>30 days of metric history** exist; per-agency configuration planned. |
| coverage drop (`headway_ai.anomaly.detect_coverage_drops`, v1) | `anomaly_coverage_drop` | `coverage_drop_threshold = 0.05` (Decimal; flags when previous coverage − current coverage strictly > threshold; rows without a coverage ratio, e.g. upt_v0 UptDetail, are skipped) | **ENGINEERING DEFAULT** — not an FTA number. Sized against the calc library's own coverage machinery (certifiability threshold 0.95, itself an engineering placeholder per `services/calc/REGULATORY_TRACKER.md`): a 0.05 drop can move a metric from comfortably-certifiable to the refusal boundary. Explicit Decimal input, recorded in every report; CLI-overridable (`--coverage-drop-threshold`). | Same statistical-baseline increment (>30 days of history); per-agency configuration planned. |
| calc-version change (`headway_ai.anomaly.detect_calc_version_changes`, v1) | `anomaly_calc_version_change` | none (fires on any `calc_version` inequality between consecutive same-metric periods) | Deterministic by construction — no threshold to source. Severity `info`: a version change is expected engineering activity; the flag exists because figures computed by different calc versions are not directly comparable, and both metric_value_ids are cited so a reviewer can walk to each version's tracker row. | none needed. |

Shared provenance notes:

- **Every flag is assistive.** Severity `blocking` is structurally
  unrepresentable in an `AnomalyFinding`; detectors flag, never correct,
  backfill, or adjust (HARD BOUNDARY, `.claude/roles/AI_SYSTEMS_ENGINEER.md`).
- **No derived number reaches prose.** Detector comparisons (deltas, ratios)
  exist only to decide whether to flag; descriptions restate the cited rows'
  raw value/coverage strings verbatim. Explanations are additionally forced
  through the grounding harness, so a derived percentage in AI prose fails
  the build (fixture `06_anomaly_fabricated_explanation_fail.json`).
- **Thresholds used are always recorded** in the frozen `AnomalyRunReport`
  (Decimal-as-text), exactly as the calc runner records its thresholds.
