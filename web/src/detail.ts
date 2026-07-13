/**
 * Plain-language translation of a figure's calculation detail
 * (computed.metric_values.detail — coverage details for vrm/vrh, UptDetail
 * for upt; see services/calc/headway_calc/types.py to_dict shapes), plus the
 * simulated-data rule over detail.source_mix.
 *
 * Translation is WORDING only: every count, ratio, and factor shown is the
 * API's string/JSON value verbatim; ratios become percentages by a
 * string-only decimal shift (src/format.ts), never through a float. Keys
 * this catalog does not know are shown raw-but-tidy (underscores become
 * spaces), never hidden — forward-compatible with future calc versions.
 */

import type { MetricValue } from "./api/types";
import { copy } from "./copy";
import { detailValueToString, ratioToPercentString } from "./format";

export type Detail = Record<string, unknown>;

/**
 * A calc version below 1.0.0 is marked PRE-VERIFICATION in
 * services/calc/REGULATORY_TRACKER.md: the calculation has not yet been
 * verified against the current FTA NTD Reporting Manual. This is a display
 * flag read off the version the API serves — the figure itself is never
 * touched client-side.
 */
export function isPreVerification(value: MetricValue): boolean {
  return value.calc_version.startsWith("0.");
}

/**
 * True when detail.source_mix names any source that is not a real feed —
 * any source name containing "simulated" (handoff 0005's simulated-data
 * rule). Such a figure must never be submitted, and the UI marks it
 * everywhere it appears.
 */
export function isSimulated(detail: Detail | undefined): boolean {
  const mix = detail?.source_mix;
  if (typeof mix !== "object" || mix === null || Array.isArray(mix)) {
    return false;
  }
  return Object.keys(mix).some((source) =>
    source.toLowerCase().includes("simulated"),
  );
}

/**
 * The honesty boundary (handoff 0014): true for an operations metric —
 * badged everywhere, never certifiable, industry-based receipt. A row
 * without the field predates migration 0024 and is an NTD-era figure.
 */
export function isOps(value: MetricValue): boolean {
  return value.category === "ops";
}

/** Detail keys that hold a ratio string, displayed as a percentage. */
const PERCENT_KEYS = new Set([
  "clean_position_share",
  "coverage_threshold",
  "missing_share",
  "missing_trip_threshold",
  "imbalance_threshold",
]);

/** Fixed display order for known scalar keys (unknowns follow, sorted). */
const KNOWN_KEY_ORDER = [
  "total_boardings_counted",
  "operated_trips",
  "trips_with_events",
  "missing_trips",
  "missing_share",
  "total_trips",
  "trips_excised",
  "total_groups",
  "blocks_touched",
  "layover_intervals_dropped",
  "clean_position_share",
  "gap_threshold_seconds",
  "coverage_threshold",
  "layover_max_seconds",
  "missing_trip_threshold",
  "imbalance_threshold",
  // ---- ops detail vocabulary (handoff 0014): otp_v0 ----
  "on_time_count",
  "early_count",
  "late_count",
  "passages_considered",
  "passages_unscheduled",
  "deviation_mean_seconds",
  "deviation_median_seconds",
  "early_tolerance_seconds",
  "late_tolerance_seconds",
  "agency_timezone",
  // ---- ops detail vocabulary: headway_adherence_v0 (cvh) ----
  "pairs_counted",
  "stops_covered",
  "routes_covered",
  "pairs_excluded_inverted",
  "pairs_excluded_over_cap",
  "pairs_excluded_unscheduled",
  "mean_scheduled_headway_seconds",
  "stddev_deviation_seconds",
  "max_scheduled_headway_seconds",
];

/**
 * The one-line "how complete is the data" summary used by report tables:
 * the coverage sentence for vrm/vrh shapes, the counted-trips sentence for
 * the UPT shape, or null when the detail reports neither.
 */
export function coverageSummary(detail: Detail | undefined): string | null {
  if (!detail) return null;
  if ("coverage" in detail) {
    return copy.detail.coverage(
      ratioToPercentString(detailValueToString(detail.coverage)),
      detailValueToString(detail.excluded_groups ?? "0"),
    );
  }
  if ("trips_with_events" in detail && "operated_trips" in detail) {
    return copy.detail.uptCounts(
      detailValueToString(detail.trips_with_events),
      detailValueToString(detail.operated_trips),
    );
  }
  return null;
}

/**
 * The refusal accounting from a figure's detail.derivation (handoff 0014,
 * design point 3 — the cadence evidence behind every ops figure): one
 * plain-language line per refusal reason, counts verbatim, NEVER hidden.
 * Empty when the detail carries no derivation block.
 */
export function refusalLines(detail: Detail | undefined): string[] {
  const derivation = detail?.derivation;
  if (
    typeof derivation !== "object" ||
    derivation === null ||
    Array.isArray(derivation)
  ) {
    return [];
  }
  const d = derivation as Record<string, unknown>;
  const s = detailValueToString;
  const lines: string[] = [];
  if ("refused_not_reached" in d) {
    lines.push(
      copy.detail.derivation.refusedNotReached(
        s(d.refused_not_reached),
        s(d.stop_radius_meters),
      ),
    );
  }
  if ("refused_endpoint_unbounded" in d) {
    lines.push(
      copy.detail.derivation.refusedEndpoint(s(d.refused_endpoint_unbounded)),
    );
  }
  if ("refused_cadence_gap" in d) {
    lines.push(
      copy.detail.derivation.refusedCadenceGap(
        s(d.refused_cadence_gap),
        s(d.max_passage_gap_seconds),
      ),
    );
  }
  return lines;
}

/**
 * The full plain-language account of detail.derivation: the versioned
 * Headway-owned method, the input counts, and the refusal lines. Keys the
 * templates consume are tracked so detailLines never double-renders them;
 * anything else inside the derivation block falls through raw-but-tidy.
 */
export function derivationLines(detail: Detail | undefined): string[] {
  const derivation = detail?.derivation;
  if (
    typeof derivation !== "object" ||
    derivation === null ||
    Array.isArray(derivation)
  ) {
    return [];
  }
  const d = derivation as Record<string, unknown>;
  const s = detailValueToString;
  const consumed = new Set([
    "derivation_name",
    "derivation_version",
    "positions_considered",
    "positions_deduplicated",
    "occurrences",
    "occurrences_skipped_few_positions",
    "min_occurrence_positions",
    "trips_observed",
    "trips_without_schedule",
    "passages_derived",
    "stops_considered",
    "refused_not_reached",
    "refused_endpoint_unbounded",
    "refused_cadence_gap",
    "stop_radius_meters",
    "max_passage_gap_seconds",
  ]);
  const lines: string[] = [
    copy.detail.derivation.method(s(d.derivation_name), s(d.derivation_version)),
    copy.detail.derivation.positions(
      s(d.positions_considered),
      s(d.positions_deduplicated),
    ),
    copy.detail.derivation.occurrences(
      s(d.occurrences),
      s(d.occurrences_skipped_few_positions),
      s(d.min_occurrence_positions),
    ),
    copy.detail.derivation.trips(
      s(d.trips_observed),
      s(d.trips_without_schedule),
    ),
    copy.detail.derivation.derived(s(d.passages_derived), s(d.stops_considered)),
    ...refusalLines(detail),
  ];
  // Derivation keys this catalog does not know yet: raw-but-tidy, never
  // dropped (forward-compatible with future derivation versions).
  for (const key of Object.keys(d).sort()) {
    if (consumed.has(key)) continue;
    lines.push(`${key.replace(/_/g, " ")}: ${s(d[key])}`);
  }
  return lines;
}

/** All detail entries as plain-language sentences, in display order. */
export function detailLines(detail: Detail): string[] {
  const lines: string[] = [];
  const consumed = new Set<string>();

  // Coverage sentence (consumes excluded_groups — it is part of the line).
  if ("coverage" in detail) {
    lines.push(coverageSummary(detail) as string);
    consumed.add("coverage");
    consumed.add("excluded_groups");
  }

  // The UPT missing-trip adjustment (FTA-sanctioned factor-up).
  if ("factor_applied" in detail) {
    consumed.add("factor_applied");
    if (detail.factor_applied === null) {
      lines.push(copy.detail.noFactorApplied);
    } else {
      lines.push(
        copy.detail.factorApplied(
          detailValueToString(detail.factor_applied),
          detailValueToString(detail.missing_trips ?? "0"),
          ratioToPercentString(
            detailValueToString(detail.missing_trip_threshold ?? ""),
          ),
        ),
      );
      // Both numbers are inside the sentence; no separate line needed.
      consumed.add("missing_trips");
      consumed.add("missing_trip_threshold");
    }
  }

  // Known scalar keys, each with its plain-language template.
  for (const key of KNOWN_KEY_ORDER) {
    if (!(key in detail) || consumed.has(key)) continue;
    const raw = detailValueToString(detail[key]);
    const shown = PERCENT_KEYS.has(key) ? ratioToPercentString(raw) : raw;
    lines.push(copy.detail.known[key](shown));
    consumed.add(key);
  }

  // Source mix — always spelled out (the simulated-data rule depends on it
  // being visible; the badge itself is rendered by the caller).
  const mix = detail.source_mix;
  if (typeof mix === "object" && mix !== null && !Array.isArray(mix)) {
    const parts = Object.entries(mix as Record<string, unknown>)
      .map(([source, count]) =>
        copy.detail.sourceMixPart(source, detailValueToString(count)),
      )
      .join(", ");
    lines.push(copy.detail.sourceMix(parts));
    consumed.add("source_mix");
  }

  // The passage-derivation accounting (ops figures, handoff 0014): the
  // versioned method, its inputs, and every refusal count — the cadence
  // evidence rides inside the figure and is always spelled out.
  if ("derivation" in detail) {
    lines.push(...derivationLines(detail));
    consumed.add("derivation");
  }

  // Anything left is a detail key this UI does not know yet: shown
  // raw-but-tidy, never dropped.
  for (const key of Object.keys(detail).sort()) {
    if (consumed.has(key)) continue;
    lines.push(`${key.replace(/_/g, " ")}: ${detailValueToString(detail[key])}`);
  }

  return lines;
}
