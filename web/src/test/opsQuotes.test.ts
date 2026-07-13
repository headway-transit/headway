/**
 * Ops-quote extraction integrity (handoff 0014, design points 1 + 5).
 *
 * quotes.json's "ops:" namespace ships the INDUSTRY basis inside every
 * operations figure — verbatim TCQSM quotes with page citations — plus the
 * explicitly Headway-owned definitions (versioned, formulas shown). These
 * tests hold the same two lines as the FTA quotes' suite:
 *  1. NO SILENT ABSENCE — both ops calcs carry at least one verified quote,
 *     their own Headway-owned definition, and the shared passage-derivation
 *     definition; the window snippet the UI depends on resolves.
 *  2. VERBATIM — the shipped text is character-for-character the text in
 *     the real services/calc/OPS_DEFINITIONS.md (not a copy), and the ops
 *     namespace never leaks into the FTA lookup or vice versa.
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  CVH_QUOTE_SNIPPET,
  OTP_WINDOW_QUOTE_SNIPPET,
  opsQuotesForCalc,
} from "../regulatory/opsQuotes";
import { quotesForCalc } from "../regulatory/quotes";

const opsDefinitionsPath = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "services",
  "calc",
  "OPS_DEFINITIONS.md",
);

const OPS_CALCS = ["otp_v0", "headway_adherence_v0"];

/** The source with blockquote markers stripped and wrapping normalized —
 *  the ONLY transformations extraction applies to quote text. */
function normalizedSource(): string {
  return readFileSync(opsDefinitionsPath, "utf8")
    .replace(/^>\s?/gm, "")
    .replace(/\s+/g, " ");
}

describe("ops quotes (quotes.json 'ops:' namespace — handoff 0014)", () => {
  it("carries, for EVERY ops calc, verified industry quotes AND both Headway-owned definitions — no silent absence", () => {
    for (const calc of OPS_CALCS) {
      const bundle = opsQuotesForCalc(calc);
      expect(
        bundle,
        `ops calc "${calc}" has no basis in quotes.json — run npm run ` +
          "extract:quotes; an ops figure must never ship without its basis",
      ).not.toBeNull();
      expect(bundle!.verified.length).toBeGreaterThanOrEqual(1);
      for (const q of bundle!.verified) {
        expect(q.quote.length).toBeGreaterThan(0);
        expect(q.citation).toContain(
          "Transit Capacity and Quality of Service Manual",
        );
      }
      // The calc's own definition leads; the shared derivation follows.
      const ownedNames = bundle!.headway_owned.map((d) => d.name);
      expect(ownedNames[0]).toBe(calc);
      expect(ownedNames).toContain("derive_stop_passages");
      for (const d of bundle!.headway_owned) {
        expect(d.reference).toBe("services/calc/OPS_DEFINITIONS.md");
        expect(d.version).toMatch(/^\d+\.\d+\.\d+$/);
        expect(d.summary.length).toBeGreaterThan(0);
      }
    }
  });

  it("ships the TCQSM on-time window VERBATIM with its p. 5-29 citation — the quote the ops receipts depend on", () => {
    const otp = opsQuotesForCalc("otp_v0")!;
    const window = otp.verified.find((q) =>
      q.quote.includes(OTP_WINDOW_QUOTE_SNIPPET),
    );
    expect(
      window,
      `no otp_v0 quote contains "${OTP_WINDOW_QUOTE_SNIPPET}" — the window ` +
        "rule must ship with every OTP receipt",
    ).toBeDefined();
    expect(window!.quote).toBe(
      "this edition of the TCQSM defines 'on-time' as a departure from a " +
        "timepoint as 1 min early to 5 min late or an arrival at the route " +
        "terminal up to 5 min late.",
    );
    expect(window!.citation).toContain("p. 5-29");
    // Character-for-character against the real OPS_DEFINITIONS.md.
    expect(normalizedSource()).toContain(`"${window!.quote}"`);
  });

  it("ships the TCQSM cvh definition VERBATIM (p. 5-30 + the Example-3 rules, p. 5-92)", () => {
    const cvh = opsQuotesForCalc("headway_adherence_v0")!;
    const definition = cvh.verified.find((q) =>
      q.quote.includes(CVH_QUOTE_SNIPPET),
    );
    expect(definition).toBeDefined();
    expect(definition!.citation).toContain("p. 5-30");
    const source = normalizedSource();
    expect(source).toContain(`"${definition!.quote}"`);
    // The population-standard-deviation rule the calc implements is quoted.
    const pstdev = cvh.verified.find((q) =>
      q.quote.includes("population standard deviation would be used"),
    );
    expect(pstdev).toBeDefined();
    expect(pstdev!.citation).toContain("p. 5-92");
    expect(source).toContain(`"${pstdev!.quote}"`);
  });

  it("ships the Headway-owned formulas VERBATIM from OPS_DEFINITIONS.md", () => {
    const source = readFileSync(opsDefinitionsPath, "utf8");
    for (const calc of OPS_CALCS) {
      const own = opsQuotesForCalc(calc)!.headway_owned.find(
        (d) => d.name === calc,
      );
      expect(own?.formula, `${calc} must ship its formula block`).toBeTruthy();
      // The fenced block, byte for byte.
      expect(source).toContain(own!.formula!);
    }
  });

  it("keeps the namespaces separate: ops calcs resolve NOTHING in the FTA lookup, and FTA calcs nothing in the ops lookup", () => {
    for (const calc of OPS_CALCS) {
      expect(quotesForCalc(calc)).toBeNull();
    }
    expect(opsQuotesForCalc("vrm_v0")).toBeNull();
    // The FTA lookup itself is unaffected by the ops namespace.
    expect(quotesForCalc("vrm_v0")).not.toBeNull();
  });
});
