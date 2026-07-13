/**
 * Quote-extraction integrity (handoff 0007, pillar 1).
 *
 * quotes.json ships the FTA rule inside every number. These tests hold two
 * lines:
 *  1. NO SILENT ABSENCE — every calc_name a figure can carry (every calc
 *     named in the web fixtures) has at least one verified quote on file.
 *     A missing entry fails the suite loudly instead of shipping silence.
 *  2. VERBATIM — the shipped quotes are character-for-character the
 *     tracker's quoted text (spot-checked against the real
 *     services/calc/REGULATORY_TRACKER.md, not a copy).
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import quotes from "../regulatory/quotes.json";
import { quoteContaining } from "../regulatory/quotes";
import type { MetricValue } from "../api/types";
import * as fixtures from "./fixtures";
import {
  SS40_QUOTE_SNIPPET,
  SS50_QUOTE_SNIPPET,
  THRESHOLD_QUOTE_SNIPPETS,
} from "../regulatory/safetyRules";
import {
  EXPANSION_FACTOR_QUOTE_SNIPPET,
  MULTIPLY_QUOTE_SNIPPET,
  OPTIONS_QUOTE_SNIPPET,
  PRECISION_FLOOR_QUOTE_SNIPPET,
  RATIO_OF_TOTALS_QUOTE_SNIPPET,
  SELECTION_QUOTE_SNIPPET,
} from "../regulatory/samplingRules";
import {
  drCallouts,
  NO_DEADHEAD_QUOTE_SNIPPET,
  NO_SHOW_REVENUE_QUOTE_SNIPPET,
  TX_ONBOARD_QUOTE_SNIPPET,
  VOMS_ATYPICAL_QUOTE_SNIPPET,
} from "../regulatory/drRules";

const quotesByCalc: Record<string, { quote: string; citation: string }[]> =
  quotes;

const trackerPath = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "services",
  "calc",
  "REGULATORY_TRACKER.md",
);

/** Every calc_name any fixture figure carries. */
function fixtureCalcNames(): string[] {
  const names = new Set<string>();
  for (const value of Object.values(fixtures)) {
    if (
      value &&
      typeof value === "object" &&
      "calc_name" in value &&
      "metric_value_id" in value
    ) {
      names.add((value as MetricValue).calc_name);
    }
  }
  return [...names].sort();
}

describe("regulatory quotes (src/regulatory/quotes.json)", () => {
  it("has at least one verified quote for EVERY calc_name in the web fixtures — no silent absence", () => {
    const names = fixtureCalcNames();
    // Guard the guard: the fixtures must actually name the position calcs
    // AND the four DR calcs the fixtures carry (handoff 0013).
    expect(names).toEqual([
      "dr_pmt_v0",
      "dr_voms_v0",
      "dr_vrh_v0",
      "dr_vrm_v0",
      "upt_v0",
      "vrh_v0",
      "vrm_v0",
    ]);
    for (const name of names) {
      const entry = quotesByCalc[name];
      expect(
        entry,
        `calc "${name}" has NO quotes in quotes.json — run npm run extract:quotes and fix the tracker mapping; a figure must never ship without its FTA rule`,
      ).toBeDefined();
      expect(entry.length).toBeGreaterThanOrEqual(1);
      for (const q of entry) {
        expect(q.quote.length).toBeGreaterThan(0);
        expect(q.citation.length).toBeGreaterThan(0);
      }
    }
  });

  it("ships the tracker's quotes VERBATIM (spot check against the real tracker file)", () => {
    const tracker = readFileSync(trackerPath, "utf8");

    // Spot quote: the Revenue Service definition shipped for vrm_v0 is the
    // exact sentence quoted in the tracker (single-line there, so a direct
    // quoted-substring check holds character for character).
    const revenueService = quotesByCalc.vrm_v0.find((q) =>
      q.citation.startsWith("Revenue Service"),
    );
    expect(revenueService).toBeDefined();
    expect(revenueService?.quote).toBe(
      "A transit vehicle is in revenue service when it is providing public transportation and is available to carry passengers. Non-public transportation activities, such as exclusive school bus service and charter service are not considered revenue service. Revenue service includes both fare and fare-free services.",
    );
    expect(tracker).toContain(`"${revenueService?.quote}"`);
    expect(revenueService?.citation).toBe(
      "Revenue Service — 2026 NTD Policy Manual, Full Reporting, p. 128",
    );

    // The same quotes back vrh_v0 (the section covers VRM and VRH).
    expect(
      quotesByCalc.vrh_v0.some((q) => q.quote === revenueService?.quote),
    ).toBe(true);

    // A hard-wrapped quote (UPT p. 143): identical to the tracker once the
    // tracker's line wrapping is normalized to single spaces — the ONLY
    // transformation extraction applies.
    const upt = quotesByCalc.upt_v0.find((q) =>
      q.citation.startsWith("UPT definition"),
    );
    expect(upt).toBeDefined();
    const normalizedTracker = tracker.replace(/\s+/g, " ");
    expect(normalizedTracker).toContain(`"${upt?.quote}"`);
    expect(upt?.citation).toBe(
      "UPT definition — 2026 NTD Policy Manual, Full Reporting, p. 143",
    );
  });

  it("ships the Safety & Security section's quotes for sscls_v0 VERBATIM (handoff 0010) — tracker emphasis unwrapped, NOTE commentary excluded", () => {
    const tracker = readFileSync(trackerPath, "utf8");
    const ss = quotesByCalc.sscls_v0;
    expect(
      ss,
      "sscls_v0 has NO quotes in quotes.json — run npm run extract:quotes; " +
        "the /safety receipts must never ship without their rules",
    ).toBeDefined();

    // The S&S-40 30-day rule: character for character, cited to the page.
    const ss40 = ss.find((q) => q.citation.startsWith("S&S-40 timing"));
    expect(ss40?.quote).toBe(
      "due no later than 30 days after the date of the event.",
    );
    expect(tracker).toContain(`"${ss40?.quote}"`);
    expect(ss40?.citation).toBe(
      "S&S-40 timing — 2026 Safety & Security Policy Manual V1, Exhibit 2, p. 4",
    );

    // The S&S-50 zero-event trap. The tracker bolds part of this quote with
    // markdown (**even if no event occurs**); unwrapping that emphasis is
    // the ONLY in-quote cleanup extraction applies.
    const ss50 = ss.find((q) => q.citation.startsWith("S&S-50 timing"));
    expect(ss50?.quote).toBe(
      "for each mode and TOS … every month, even if no event occurs",
    );
    expect(tracker.replaceAll("**", "")).toContain(`"${ss50?.quote}"`);

    // The injury threshold quote the entry form's plain question maps to.
    const injury = ss.find((q) => q.quote.startsWith("Immediate transport"));
    expect(injury?.quote).toBe(
      "Immediate transport away from the scene for medical attention for one or more persons.",
    );
    expect(injury?.citation).toBe(
      "Major-event thresholds — 2026 Safety & Security Policy Manual V1, Exhibit 5, p. 16",
    );

    // The NOTE guard: the tracker's verification-method commentary quotes
    // spellings ("Cyber Security" vs "cybersecurity") ABOUT the manual, not
    // from a rule; neither may ship as a verified quote.
    for (const q of ss) {
      expect(q.quote).not.toBe("cybersecurity");
      expect(q.quote).not.toBe("Cyber Security");
    }
  });

  it("resolves EVERY quote snippet the /safety UI depends on — no silent absence in the receipts or the deadline citations", () => {
    for (const [token, snippet] of Object.entries(THRESHOLD_QUOTE_SNIPPETS)) {
      expect(
        quoteContaining("sscls_v0", snippet),
        `threshold "${token}" maps to a snippet with no verified quote on file`,
      ).not.toBeNull();
    }
    expect(quoteContaining("sscls_v0", SS40_QUOTE_SNIPPET)).not.toBeNull();
    expect(quoteContaining("sscls_v0", SS50_QUOTE_SNIPPET)).not.toBeNull();
  });

  it("ships the NTD Sampling Manual section's quotes for sampling_v0 VERBATIM and resolves EVERY snippet the /sampling UI depends on (handoff 0012)", () => {
    const tracker = readFileSync(trackerPath, "utf8");
    const sampling = quotesByCalc.sampling_v0;
    expect(
      sampling,
      "sampling_v0 has NO quotes in quotes.json — run npm run extract:quotes; " +
        "the /sampling wizard, worksheets, and estimate receipt must never " +
        "ship without their rules",
    ).toBeDefined();

    // The §83.05 rule — ratio of totals (a) AND the (b) ban — character
    // for character, present in the real tracker.
    const ratio = quoteContaining("sampling_v0", RATIO_OF_TOTALS_QUOTE_SNIPPET);
    expect(ratio?.quote).toBe(
      "(a) You must determine the sample APTL for a given sample as the ratio of sample total PMT over sample total UPT for the following cases: (1) for the entire sample, (2) by type of service days, or (3) by service group. (b) You must not determine the sample APTL as the average of the APTL across individual service units in the sample.",
    );
    expect(tracker).toContain(`"${ratio?.quote}"`);
    expect(ratio?.citation).toBe(
      "§83.05 — FTA NTD Sampling Manual, March 31, 2009, p. 42",
    );

    // The §83.01 expansion-factor rule (a label with parenthesized
    // sub-refs — the head parse must still cite the PAGE, not the "(a)").
    const expansion = quoteContaining(
      "sampling_v0",
      EXPANSION_FACTOR_QUOTE_SNIPPET,
    );
    expect(expansion?.quote).toBe(
      "(a) You must use your 100% count of UPT as the expansion factor. (b) For estimating average daily PMT by type of service days, use your annual total 100% count of UPT by type of service days.",
    );
    expect(expansion?.citation).toBe(
      "§83.01(a)/(b) — FTA NTD Sampling Manual, March 31, 2009, p. 42",
    );

    // The §63.03 selection rule the worksheets carry.
    const selection = quoteContaining("sampling_v0", SELECTION_QUOTE_SNIPPET);
    expect(selection?.citation).toBe(
      "§63.03 — FTA NTD Sampling Manual, March 31, 2009, p. 19",
    );
    expect(selection?.quote).toContain(
      "(1) sampling under the method is random. (2) sampling under the method is without replacement.",
    );

    // Every remaining snippet the /sampling UI depends on resolves.
    expect(quoteContaining("sampling_v0", OPTIONS_QUOTE_SNIPPET)).not.toBeNull();
    expect(quoteContaining("sampling_v0", MULTIPLY_QUOTE_SNIPPET)).not.toBeNull();
    expect(
      quoteContaining("pmt_v0", PRECISION_FLOOR_QUOTE_SNIPPET),
    ).not.toBeNull();
  });

  it("ships the Demand Response section's quotes for ALL FIVE dr calcs VERBATIM and resolves EVERY snippet the DR receipts depend on (handoff 0013)", () => {
    const tracker = readFileSync(trackerPath, "utf8");
    const drCalcs = [
      "dr_pmt_v0",
      "dr_upt_v0",
      "dr_voms_v0",
      "dr_vrh_v0",
      "dr_vrm_v0",
    ];
    for (const calc of drCalcs) {
      expect(
        quotesByCalc[calc],
        `${calc} has NO quotes in quotes.json — run npm run extract:quotes; ` +
          "a DR figure must never ship without its rule",
      ).toBeDefined();
      expect(quotesByCalc[calc].length).toBeGreaterThanOrEqual(1);
    }

    // The TX onboard-only rule — character for character, cited to p. 129
    // of the manual named on the DR section's (unbolded) Source line.
    const tx = quoteContaining("dr_vrh_v0", TX_ONBOARD_QUOTE_SNIPPET);
    expect(tx?.quote).toBe(
      "agencies must report only the miles and hours when a transit passenger is onboard as revenue service. When a transit passenger is not onboard, the service is not reportable to the NTD.",
    );
    expect(tracker).toContain(`"${tx?.quote}"`);
    expect(tx?.citation).toBe(
      "TX revenue rule — 2026 NTD Full Reporting Policy Manual, p. 129",
    );

    // The TX/TN no-deadhead rule, cited to p. 130.
    const deadhead = quoteContaining("dr_vrm_v0", NO_DEADHEAD_QUOTE_SNIPPET);
    expect(deadhead?.quote).toBe(
      "Full Reporters do not report deadhead for the Vanpool mode or the TX and Transportation Network Company (TN) TOS.",
    );
    expect(tracker).toContain(`"${deadhead?.quote}"`);
    expect(deadhead?.citation).toBe(
      "Non-fixed-route deadhead legs — 2026 NTD Full Reporting Policy Manual, p. 130",
    );

    // The Exhibit 36 no-show row (revenue yes / boarding no).
    const noShow = quoteContaining("dr_vrh_v0", NO_SHOW_REVENUE_QUOTE_SNIPPET);
    expect(noShow?.quote).toBe(
      "Driver travels to pick up a passenger but the passenger is a no-show",
    );
    expect(tracker).toContain(`"${noShow?.quote}"`);

    // The DR VOMS atypical-day INCLUSION (Exhibits 38 + 40).
    const atypical = quoteContaining(
      "dr_voms_v0",
      VOMS_ATYPICAL_QUOTE_SNIPPET,
    );
    expect(atypical?.quote).toBe(
      "The largest number of vehicles in revenue service at any one time during the reporting year (INCLUDES atypical service)",
    );
    expect(atypical?.citation).toBe(
      "DR VOMS — 2026 NTD Full Reporting Policy Manual, Exhibits 38 + 40, pp. 138–139",
    );

    // Every callout the Receipt can emit resolves for every DR calc and
    // TOS combination — no silent absence in any DR receipt.
    const metrics = ["vrh", "vrm", "upt", "voms", "pmt"];
    const calcByMetric: Record<string, string> = {
      vrh: "dr_vrh_v0",
      vrm: "dr_vrm_v0",
      upt: "dr_upt_v0",
      voms: "dr_voms_v0",
      pmt: "dr_pmt_v0",
    };
    for (const metric of metrics) {
      for (const tos of [null, "DO", "PT", "TX", "TN"]) {
        for (const callout of drCallouts(metric, tos)) {
          expect(
            quoteContaining(calcByMetric[metric], callout.snippet),
            `callout "${callout.key}" (${metric}, tos ${tos}) has no verified quote on file`,
          ).not.toBeNull();
        }
      }
    }
  });
});
