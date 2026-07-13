/**
 * The /sampling UI's map to the VERIFIED NTD Sampling Manual quotes in
 * quotes.json (handoff 0012). Each snippet locates one quote via
 * quoteContaining(); src/test/quotes.test.ts fails the suite if any
 * snippet here stops resolving — the wizard, the worksheet, and the
 * estimate receipt must never ship without their rules.
 *
 * sampling_v0 quotes come from the tracker's "Verified — NTD Sampling
 * Manual" section and its "Sampling plan tables — implementation quotes"
 * subsection; the pmt_v0 snippet is the 2026 Policy Manual's estimation
 * floor (p. 149). These are the rules the UI itself places next to its
 * controls. Regulatory text the API serves (eligibility guidance, the
 * table-cell citation, the undersampling/oversampling citations, the
 * estimate's method label, citations, and caveats) is rendered VERBATIM
 * from the response instead — never restated here.
 */

/** §41.07(c) — the three efficiency options, verbatim (sampling_v0). */
export const OPTIONS_QUOTE_SNIPPET =
  "APTL Option – you must report a 100% count of UPT";

/** §63.03(b) — random AND without-replacement selection (sampling_v0). */
export const SELECTION_QUOTE_SNIPPET =
  "Without replacement means that the method will not select the same service unit more than once";

/**
 * §83.05 — the sample APTL is a RATIO OF TOTALS (a), and the (b) ban on
 * averaging per-unit APTLs (sampling_v0).
 */
export const RATIO_OF_TOTALS_QUOTE_SNIPPET =
  "ratio of sample total PMT over sample total UPT for the following cases";

/** §83.01 — the expansion factor IS the 100% UPT count (sampling_v0). */
export const EXPANSION_FACTOR_QUOTE_SNIPPET =
  "You must use your 100% count of UPT as the expansion factor";

/** §83.07 — estimated PMT = sample APTL × expansion factor (sampling_v0). */
export const MULTIPLY_QUOTE_SNIPPET =
  "multiply your sample APTL for the entire annual sample with your corresponding annual expansion factor";

/**
 * p. 149 — the estimation floor the ready-to-use plans are designed to meet
 * (pmt_v0: the 2026 Policy Manual's estimation-floor bullet).
 */
export const PRECISION_FLOOR_QUOTE_SNIPPET =
  "Minimum confidence of 95 percent";
