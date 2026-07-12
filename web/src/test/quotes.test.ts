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
    // Guard the guard: the fixtures must actually name the three calcs.
    expect(names).toEqual(["upt_v0", "vrh_v0", "vrm_v0"]);
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
});
