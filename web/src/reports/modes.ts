/**
 * The dashboard's mode dimension (handoff 0041, design point 1–3).
 *
 * BINDING RULES, enforced here and by src/test/modes.test.tsx:
 *
 * 1. **Data-driven, never hardcoded.** The selectable modes are exactly the
 *    distinct `mode:*` scopes present in the figures the API served, plus
 *    the agency rollup as the default. There is no list of modes in this
 *    file — a hardcoded mode that can only ever show zero would be a lie,
 *    and Rideshare/Via/Arc must appear the day their calc waves land
 *    WITHOUT a frontend change.
 * 2. **Re-scope, never derive.** Selecting a mode is a FILTER over the
 *    persisted rows (`scope === "mode:bus"`), nothing else. Nothing in this
 *    module sums, averages, or synthesizes a per-mode figure; every figure
 *    shown under a mode is the calculation service's own row, verbatim,
 *    with its own metric_value_id receipt.
 * 3. **Labels are lookups, never guesses.** `mode:DR` uses the NTD code
 *    vocabulary; GTFS-derived scopes use the transform's lowercase names
 *    (`mode:bus`) — the two namespaces never collide (see drRules.ts). An
 *    unrecognised code renders as the raw code, honestly.
 */

import { copy } from "../copy";
import { drTosLabel } from "./../regulatory/drRules";

/** The agency-wide rollup: the default selection, a persisted scope of its
 *  own — never a total the browser computed from the modes below it. */
export const AGENCY_SCOPE = "agency";

/** Scopes the agency-wide view accepts (the fleet-wide persisted rows). */
const AGENCY_SCOPES = new Set([AGENCY_SCOPE, "fleet"]);

/** Above this many modes the segmented control becomes a dropdown. */
export const MODE_SEGMENT_MAX = 5;

export interface ModeOption {
  /** The persisted scope string, verbatim — this IS the filter. */
  scope: string;
  /** Plain-language label; falls back to the raw code, honestly. */
  label: string;
}

/** True for the agency-wide rollup selection. */
export function isAgencyScope(scope: string): boolean {
  return AGENCY_SCOPES.has(scope);
}

/**
 * Does this row belong to the selected scope? Exact string match for a
 * mode (a DR type-of-service scope is its own mode entry, never folded into
 * `mode:DR` — folding would need arithmetic nobody performed); the agency
 * selection accepts the fleet-wide scopes only.
 */
export function rowInScope(rowScope: string, selected: string): boolean {
  return isAgencyScope(selected)
    ? isAgencyScope(rowScope)
    : rowScope === selected;
}

/** Plain-language label for one mode code (no scope prefix). */
export function modeCodeLabel(code: string): string {
  if (code === "unknown") return copy.dashboard.mode.unknownMode;
  return (
    copy.safety.modeLabels[code] ??
    copy.report.mr20.modeLabels[code] ??
    code
  );
}

/**
 * Plain-language label for a persisted `mode:*` scope.
 * `mode:bus` → "Bus"; `mode:DR` → "Demand response (DR)";
 * `mode:DR:tos:TX` → "Demand response (DR) — Taxi (TX)".
 * Any other shape renders verbatim (never guessed at).
 */
export function modeScopeLabel(scope: string): string {
  if (!scope.startsWith("mode:")) return scope;
  const rest = scope.slice("mode:".length);
  const parts = rest.split(":");
  const base = modeCodeLabel(parts[0]);
  if (parts.length === 3 && parts[1] === "tos") {
    return copy.dashboard.mode.tosLabel(base, drTosLabel(parts[2]));
  }
  return parts.length === 1 ? base : `${base} (${parts.slice(1).join(":")})`;
}

/**
 * The selectable modes: every distinct `mode:*` scope present in the served
 * rows, label-sorted for a stable order. NOT a catalogue of modes that
 * exist in the world — a catalogue of modes that have persisted figures.
 */
export function modeOptions(rows: { scope: string }[]): ModeOption[] {
  const scopes = new Set<string>();
  for (const row of rows) {
    if (row.scope.startsWith("mode:")) scopes.add(row.scope);
  }
  return [...scopes]
    .map((scope) => ({ scope, label: modeScopeLabel(scope) }))
    .sort((a, b) =>
      a.label === b.label
        ? a.scope < b.scope
          ? -1
          : 1
        : a.label < b.label
          ? -1
          : 1,
    );
}

/** The label for whatever is selected (agency default included). */
export function selectedModeLabel(scope: string): string {
  return isAgencyScope(scope)
    ? copy.dashboard.mode.allModes
    : modeScopeLabel(scope);
}
