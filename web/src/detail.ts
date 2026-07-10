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

import { copy } from "./copy";
import { detailValueToString, ratioToPercentString } from "./format";

export type Detail = Record<string, unknown>;

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

  // Anything left is a detail key this UI does not know yet: shown
  // raw-but-tidy, never dropped.
  for (const key of Object.keys(detail).sort()) {
    if (consumed.has(key)) continue;
    lines.push(`${key.replace(/_/g, " ")}: ${detailValueToString(detail[key])}`);
  }

  return lines;
}
