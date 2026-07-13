/**
 * The industry basis inside an OPERATIONS number (handoff 0014, design
 * points 1 + 5). Ops metrics (`category === "ops"`) are never FTA figures:
 * their receipts cite a VERIFIED industry source (the TCQSM, quoted verbatim
 * with page citations) plus the explicitly Headway-owned definitions
 * (versioned, formulas shown) — and the two must never be confusable, with
 * each other or with the FTA quotes NTD receipts carry.
 *
 * Both live in src/regulatory/quotes.json under "ops:"-namespaced keys,
 * generated — never hand-edited — by scripts/extract-quotes.mjs from
 * services/calc/OPS_DEFINITIONS.md (the namespacing rationale is documented
 * in that script's header: one file keeps the CI drift gate covering ops
 * text too; the prefix keeps the FTA namespace unmixed). Regenerate with:
 * npm run extract:quotes
 *
 * Callers MUST treat a null lookup as a loud condition (state the absence),
 * never as "render nothing".
 */

import quotesJson from "./quotes.json";

/** Verbatim TCQSM text with its page citation — a VERIFIED industry quote. */
export interface OpsVerifiedQuote {
  quote: string;
  citation: string;
}

/** An explicitly Headway-owned operational definition — OURS, not a rule. */
export interface OpsOwnedDefinition {
  /** e.g. "otp_v0" or "derive_stop_passages". */
  name: string;
  /** The definition's own version (changing it mints a new version). */
  version: string;
  /** The definition's lead paragraph, verbatim (owner / lead-in sentence). */
  summary: string;
  /** The fenced formula block, verbatim — null when the section has none. */
  formula: string | null;
  /** Where the full definition lives: services/calc/OPS_DEFINITIONS.md. */
  reference: string;
}

export interface OpsQuoteBundle {
  verified: OpsVerifiedQuote[];
  headway_owned: OpsOwnedDefinition[];
}

const opsByCalc: Record<string, OpsQuoteBundle> = Object.fromEntries(
  Object.entries(quotesJson as Record<string, unknown>)
    .filter(([key, value]) => key.startsWith("ops:") && !Array.isArray(value))
    .map(([key, value]) => [key.slice("ops:".length), value as OpsQuoteBundle]),
);

/**
 * The ops basis for one calc_name, or null when none is on file — a LOUD
 * condition for callers (the receipt states the absence, never blanks).
 */
export function opsQuotesForCalc(calcName: string): OpsQuoteBundle | null {
  const bundle = opsByCalc[calcName];
  return bundle && bundle.verified.length > 0 ? bundle : null;
}

/**
 * Snippets the ops UI depends on being present VERBATIM — pinned by
 * src/test/opsQuotes.test.ts so a drifted OPS_DEFINITIONS.md fails the suite
 * before it ships a receipt without its window rule.
 */
export const OTP_WINDOW_QUOTE_SNIPPET = "1 min early to 5 min late";
export const CVH_QUOTE_SNIPPET = "coefficient of variation of headways";
