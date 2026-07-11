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
import type { MetricValue } from "../api/types";
import * as fixtures from "./fixtures";

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
});
