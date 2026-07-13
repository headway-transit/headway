/**
 * The FTA rule inside the number (handoff 0007, pillar 1).
 *
 * quotes.json is generated — never hand-edited — by scripts/extract-quotes.mjs
 * from services/calc/REGULATORY_TRACKER.md's "Verified definitions" sections:
 * the verbatim, page-cited FTA NTD Policy Manual quotes the NTD/Compliance
 * Engineer verified for each calc. Regenerate with:  npm run extract:quotes
 *
 * The UI renders these quotes EXACTLY as extracted (blockquote + cite). It
 * never paraphrases, never generates, and never hides an absence: a calc with
 * no quotes on file is reported loudly by the Receipt (and fails the test
 * suite — see src/test/quotes.test.ts).
 */

import quotesJson from "./quotes.json";

export interface RegulatoryQuote {
  /** Verbatim FTA NTD Policy Manual text, exactly as quoted in the tracker. */
  quote: string;
  /** Topic label — manual name, page reference (verbatim from the tracker). */
  citation: string;
}

/**
 * FTA entries only: the "ops:"-namespaced keys (operations metrics, handoff
 * 0014 — TCQSM quotes + Headway-owned definitions, a different shape read by
 * src/regulatory/opsQuotes.ts) are filtered OUT here so an ops basis can
 * never be served as an FTA rule, nor the reverse.
 */
const quotesByCalc: Record<string, RegulatoryQuote[]> = Object.fromEntries(
  Object.entries(quotesJson as Record<string, unknown>).filter(
    ([key, value]) => !key.startsWith("ops:") && Array.isArray(value),
  ),
) as Record<string, RegulatoryQuote[]>;

/**
 * The verified quotes for one calc_name, or null when none are on file.
 * Callers MUST treat null as a loud condition (show the absence), never as
 * "render nothing".
 */
export function quotesForCalc(calcName: string): RegulatoryQuote[] | null {
  const quotes = quotesByCalc[calcName];
  return quotes && quotes.length > 0 ? quotes : null;
}

/**
 * The single verified quote for one calc whose text contains `snippet`
 * (used to place a SPECIFIC rule next to the UI element it governs, e.g.
 * the S&S-40 30-day rule beside its deadline). Returns null when no quote
 * matches — a LOUD condition for callers (state the absence; never render
 * an unverified paraphrase in its place), and a test-suite failure for
 * every snippet the UI relies on (src/test/quotes.test.ts).
 */
export function quoteContaining(
  calcName: string,
  snippet: string,
): RegulatoryQuote | null {
  const quotes = quotesByCalc[calcName] ?? [];
  return quotes.find((q) => q.quote.includes(snippet)) ?? null;
}
