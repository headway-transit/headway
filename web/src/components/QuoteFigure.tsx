/**
 * The ONE rendering of "the FTA rule inside the number" (handoff 0007,
 * pillar 1): a verbatim manual quote from src/regulatory/quotes.json as a
 * blockquote + citation — the fta-quote pattern. Extracted 2026-07-13 from
 * the four identical copies in Receipt.tsx, SafetyView.tsx (×2), and
 * SamplingView.tsx, converging on Receipt.tsx's shape; the markup and class
 * names are unchanged, so every existing receipt renders byte-for-byte the
 * same figure.
 *
 * A missing quote is NEVER blank — the caller's plain-language absence
 * message renders instead:
 *
 *  - default (loud): `<p class="alert">` — a rule that should be on file but
 *    is not is a defect the reader must see (regenerate the quotes, or the
 *    figure ships without its rule).
 *  - variant="gap" (deliberately muted, `threshold-quote-missing`): for
 *    classifier tokens the tracker KNOWINGLY has no verbatim quote for
 *    (src/regulatory/safetyRules.ts — today only non_major_fire, whose p. 3
 *    "non-major fires" scope line is a tracker summary, not a quotation).
 *    Those tokens appear on every receipt that meets them, so a loud alert
 *    would cry wolf on perfectly healthy output; the stated gap stays
 *    readable but must not look like a failure.
 */

import type { RegulatoryQuote } from "../regulatory/quotes";

export interface QuoteFigureProps {
  /** The verified quote, or null when no quote is on file. */
  quote: RegulatoryQuote | null;
  /** Shown (never silently skipped) when `quote` is null. */
  missingMessage: string;
  /** "alert" (default): loud absence. "gap": deliberately muted absence. */
  variant?: "alert" | "gap";
}

export function QuoteFigure({
  quote,
  missingMessage,
  variant = "alert",
}: QuoteFigureProps) {
  if (!quote) {
    return (
      <p className={variant === "gap" ? "threshold-quote-missing" : "alert"}>
        {missingMessage}
      </p>
    );
  }
  return (
    <figure className="fta-quote">
      <blockquote>
        <p>{quote.quote}</p>
      </blockquote>
      <figcaption>
        <cite>{quote.citation}</cite>
      </figcaption>
    </figure>
  );
}
