/**
 * WCAG 2.1 contrast math for the basemap styles (handoff 0043, design
 * point 3: "contrast is verified, not eyeballed").
 *
 * The app's design tokens are gated by `scripts/check-contrast.mjs`, which
 * carries a hand-copied table of hex pairs. The BASEMAP cannot work that
 * way: its colors live in the two authored style files
 * (`src/map/styles/headway-basemap-*.json`) and there are ~90 of them per
 * style. So each style file carries its OWN check list, expressed as
 * *theme keys* rather than literal hex — change a color and the gate
 * re-measures the new color automatically; it can never drift out of sync
 * with the thing it is gating.
 *
 * Two bars, both from WCAG 2.1:
 *   - labels are text            → SC 1.4.3, >= 4.5:1
 *   - roads/water are graphical  → SC 1.4.11 (non-text contrast), >= 3:1
 *     objects you must perceive     (a street you cannot see is a street
 *                                    that is not on the map)
 *
 * The "best stroke wins" rule for roads: a street is drawn as a fill with
 * a casing under it, and which of the two carries the contrast depends on
 * the ground. On the dark style the bright fill separates the street from
 * a near-black ground; on the light style the fill is white-on-cream (by
 * cartographic convention) and the dark CASING is what makes the street
 * visible. A road check therefore lists both keys and passes when the
 * better of the two clears the bar — but BOTH numbers are always reported,
 * so nobody can hide a weak stroke behind a strong one.
 */

/** One sRGB channel, linearized (WCAG 2.1 relative-luminance definition). */
function srgbChannel(value: number): number {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/** WCAG 2.1 relative luminance of a `#rrggbb` color. */
export function luminance(hex: string): number {
  const h = hex.replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(h)) {
    throw new Error(`not a #rrggbb color: ${hex}`);
  }
  return (
    0.2126 * srgbChannel(parseInt(h.slice(0, 2), 16)) +
    0.7152 * srgbChannel(parseInt(h.slice(2, 4), 16)) +
    0.0722 * srgbChannel(parseInt(h.slice(4, 6), 16))
  );
}

/** WCAG 2.1 contrast ratio between two `#rrggbb` colors (1 … 21). */
export function contrastRatio(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/** Rounded to two decimals — the form recorded in handoff evidence. */
export function ratio(a: string, b: string): number {
  return Math.round(contrastRatio(a, b) * 100) / 100;
}

/** A check as written in a style file: theme keys, not literal colors. */
export interface ContrastCheck {
  /** Plain-language name of the pair, for the recorded evidence table. */
  what: string;
  /** Which bar applies (drives the target and the report grouping). */
  kind: "road" | "water" | "label";
  /** The required ratio. */
  min: number;
  /** Theme key of the ground/background this is measured against. */
  bg: string;
  /** Theme keys of the strokes that could carry the contrast; the BEST
   *  one must clear `min`. Single-entry for labels and water. */
  fg: string[];
}

/** One measured check, ready to print or assert on. */
export interface ContrastResult {
  what: string;
  kind: ContrastCheck["kind"];
  min: number;
  /** Every stroke measured, in the order the style listed them. */
  measured: { key: string; color: string; ratio: number }[];
  bg: { key: string; color: string };
  /** The best of `measured` — the number the gate judges. */
  best: number;
  pass: boolean;
}

/**
 * Measure one check against a resolved theme.
 *
 * Throws (rather than skipping) on an unknown key: a check that silently
 * measured nothing would be worse than no check at all.
 */
export function measureCheck(
  check: ContrastCheck,
  theme: Record<string, unknown>,
): ContrastResult {
  const colorOf = (key: string): string => {
    const value = theme[key];
    if (typeof value !== "string") {
      throw new Error(`contrast check "${check.what}": no theme color "${key}"`);
    }
    return value;
  };
  const bgColor = colorOf(check.bg);
  const measured = check.fg.map((key) => {
    const color = colorOf(key);
    return { key, color, ratio: ratio(color, bgColor) };
  });
  const best = measured.reduce((acc, m) => Math.max(acc, m.ratio), 0);
  return {
    what: check.what,
    kind: check.kind,
    min: check.min,
    measured,
    bg: { key: check.bg, color: bgColor },
    best,
    pass: best >= check.min,
  };
}

/** Measure every check a style declares. */
export function measureStyle(style: {
  contrastChecks: ContrastCheck[];
  theme: Record<string, unknown>;
}): ContrastResult[] {
  return style.contrastChecks.map((c) => measureCheck(c, style.theme));
}
