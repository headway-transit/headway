/**
 * The Demand Response receipt affordance (handoff 0013, design point 5):
 * the mode/TOS badge and the rule callouts for DR-scoped figures.
 *
 * DR figures persist under scope `mode:DR` (whole mode) and
 * `mode:DR:tos:<tos>` (one type of service: DO|PT|TX|TN) — never `agency`.
 * `mode:DR` uses the NTD mode code (the demand_response_trip wire
 * contract's vocabulary); GTFS-derived scopes use lowercase transform
 * names (`mode:bus`), so the namespaces never collide and this parser
 * matches the DR shape exactly.
 *
 * The TOS selects the revenue rule (the reason a mixed-TOS vehicle-day is
 * excluded upstream), so receipts quote the specific verified rule wherever
 * the TOS changes what the number means — via quoteContaining() over the
 * tracker's "Verified — Demand Response / on-demand reporting" quotes in
 * quotes.json. src/test/quotes.test.ts fails the suite if any snippet here
 * stops resolving: a DR figure must never ship without its rule.
 */

/** `mode:DR` or `mode:DR:tos:<tos>`, parsed; null for any other scope. */
export interface DrScope {
  /** The type-of-service code (DO|PT|TX|TN), or null for the whole mode. */
  tos: string | null;
}

export function parseDrScope(scope: string): DrScope | null {
  if (scope === "mode:DR") return { tos: null };
  const m = /^mode:DR:tos:([A-Z0-9]+)$/.exec(scope);
  return m ? { tos: m[1] } : null;
}

/**
 * Plain-language TOS labels (2026 NTD Policy Manual pp. 37–39 taxonomy).
 * An unknown code falls back to the raw code — shown honestly, never
 * guessed at (the modeLabels convention).
 */
export const DR_TOS_LABELS: Record<string, string> = {
  DO: "Directly operated (DO)",
  PT: "Purchased transportation (PT)",
  TX: "Taxi (TX)",
  TN: "Transportation Network Company (TN)",
};

export function drTosLabel(tos: string): string {
  return DR_TOS_LABELS[tos] ?? tos;
}

// ---- quote snippets the DR callouts place next to the figures they govern.

/** p. 129 — TX counts ONLY passenger-onboard miles/hours as revenue. */
export const TX_ONBOARD_QUOTE_SNIPPET =
  "report only the miles and hours when a transit passenger is onboard";

/** p. 130 — no deadhead is reported for the TX and TN types of service. */
export const NO_DEADHEAD_QUOTE_SNIPPET =
  "Full Reporters do not report deadhead for the Vanpool mode or the TX and Transportation Network Company (TN) TOS";

/** Exhibit 36 (pp. 134–135) — the no-show visit is REVENUE time/miles. */
export const NO_SHOW_REVENUE_QUOTE_SNIPPET =
  "Driver travels to pick up a passenger but the passenger is a no-show";

/** Exhibits 38 + 40 (pp. 138–139) — DR VOMS INCLUDES atypical days. */
export const VOMS_ATYPICAL_QUOTE_SNIPPET = "INCLUDES atypical service";

/** One rule callout: a plain-language lead-in key + the quote to locate. */
export interface DrCallout {
  /** Stable key naming the rule; also selects the copy.dr.callouts line. */
  key: "txOnboard" | "noDeadhead" | "noShowRevenue" | "vomsAtypical";
  snippet: string;
}

/**
 * The rule callouts for one DR-scoped figure, by metric code and TOS.
 * Only rules that change THIS figure's semantics are called out (the full
 * verified quote list renders below them on every receipt):
 *
 * - vrh/vrm: the Exhibit 36 no-show-is-revenue rule — except under TX,
 *   where the p. 129 onboard-only rule replaces the span semantics (a
 *   no-show contributes nothing to TX, so quoting the no-show row there
 *   would state the wrong rule). The whole-mode figure aggregates DO/PT/TX
 *   vehicle-days, so it carries the general rule.
 * - TX vrh/vrm/voms: the p. 129 onboard-only rule (VOMS sweeps the same
 *   merged onboard windows the hours/miles price).
 * - TX/TN vrh/vrm: the p. 130 no-deadhead rule.
 * - voms: the Exhibits 38+40 atypical-day INCLUSION (the divergence from
 *   the fleet VOMS calc's atypical-day exclusion).
 */
export function drCallouts(metric: string, tos: string | null): DrCallout[] {
  const callouts: DrCallout[] = [];
  const hoursOrMiles = metric === "vrh" || metric === "vrm";

  if (tos === "TX" && (hoursOrMiles || metric === "voms")) {
    callouts.push({ key: "txOnboard", snippet: TX_ONBOARD_QUOTE_SNIPPET });
  }
  if ((tos === "TX" || tos === "TN") && hoursOrMiles) {
    callouts.push({ key: "noDeadhead", snippet: NO_DEADHEAD_QUOTE_SNIPPET });
  }
  if (hoursOrMiles && tos !== "TX") {
    callouts.push({
      key: "noShowRevenue",
      snippet: NO_SHOW_REVENUE_QUOTE_SNIPPET,
    });
  }
  if (metric === "voms") {
    callouts.push({
      key: "vomsAtypical",
      snippet: VOMS_ATYPICAL_QUOTE_SNIPPET,
    });
  }
  return callouts;
}
