/**
 * Colour-vision-deficiency simulation, so "CVD-safe" is a MEASUREMENT
 * rather than a claim (handoff 0043, design point 4).
 *
 * The mode marks encode mode in two channels: SHAPE (the family) and
 * COLOUR (the mode inside that family). Shape already separates one family
 * from another, so the only colours that colour ALONE must separate are the
 * ones drawn with the SAME glyph. Those pairs are the ones this module
 * gates — and it gates them the way the basemap contrast gate works: by
 * re-measuring the palette that actually ships, never by trusting a table
 * somebody typed once.
 *
 * The simulation is Viénot, Brettel & Mollon (1999), "Digital video
 * colourmaps for checking the legibility of displays by dichromats"
 * (Color Research & Application 24(4):243-252) — the standard reduced LMS
 * projection for protanopia and deuteranopia, plus the tritanopia plane
 * from the same construction. It is an approximation of dichromat
 * perception, not a claim about any individual's vision; that is why the
 * mark palette ALSO separates every same-shape pair by relative luminance,
 * a channel no colour-vision deficiency removes (see marks.ts).
 *
 * Separation is reported as CIE76 ΔE in L*a*b* (D65) — a plain distance,
 * chosen because it is transparent and reproducible rather than because it
 * is the most perceptually refined formula available.
 */

/** The three dichromacies the gate simulates. */
export type CvdKind = "protan" | "deutan" | "tritan";

export const CVD_KINDS: CvdKind[] = ["protan", "deutan", "tritan"];

/** Plain-language names, for the printed gate report. */
export const CVD_NAMES: Record<CvdKind, string> = {
  protan: "protanopia (no red cones)",
  deutan: "deuteranopia (no green cones)",
  tritan: "tritanopia (no blue cones)",
};

function srgbToLinear(value: number): number {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

function linearToSrgb(value: number): number {
  const c = Math.min(1, Math.max(0, value));
  const s = c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
  return Math.round(s * 255);
}

/** `#rrggbb` → the three linear-light channels. Throws on a bad colour. */
export function toLinearRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(h)) {
    throw new Error(`not a #rrggbb color: ${hex}`);
  }
  return [
    srgbToLinear(parseInt(h.slice(0, 2), 16)),
    srgbToLinear(parseInt(h.slice(2, 4), 16)),
    srgbToLinear(parseInt(h.slice(4, 6), 16)),
  ];
}

/** Linear-light channels → `#RRGGBB`. */
export function fromLinearRgb(rgb: [number, number, number]): string {
  return (
    "#" +
    rgb
      .map((c) => linearToSrgb(c).toString(16).padStart(2, "0"))
      .join("")
      .toUpperCase()
  );
}

/**
 * Simulate how a dichromat sees a colour (Viénot et al. 1999).
 *
 * Linear sRGB → LMS (Hunt-Pointer-Estevez), collapse the missing cone onto
 * the plane the remaining two span, then back to linear sRGB.
 */
export function simulateCvd(hex: string, kind: CvdKind): string {
  const [r, g, b] = toLinearRgb(hex);
  const l = 17.8824 * r + 43.5161 * g + 4.11935 * b;
  const m = 3.45565 * r + 27.1554 * g + 3.86714 * b;
  const s = 0.0299566 * r + 0.184309 * g + 1.46709 * b;
  let l2 = l;
  let m2 = m;
  let s2 = s;
  if (kind === "protan") l2 = 2.02344 * m - 2.52581 * s;
  if (kind === "deutan") m2 = 0.494207 * l + 1.24827 * s;
  if (kind === "tritan") s2 = -0.395913 * l + 0.801109 * m;
  return fromLinearRgb([
    0.080944 * l2 - 0.130504 * m2 + 0.116721 * s2,
    -0.0102485 * l2 + 0.0540194 * m2 - 0.113615 * s2,
    -0.000365294 * l2 - 0.00412163 * m2 + 0.693513 * s2,
  ]);
}

/** CIE L*a*b* (D65 white point) of a `#rrggbb` colour. */
export function toLab(hex: string): [number, number, number] {
  const [r, g, b] = toLinearRgb(hex);
  const x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047;
  const y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883;
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const [fx, fy, fz] = [f(x), f(y), f(z)];
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

/** CIE76 ΔE between two colours, rounded to one decimal. */
export function deltaE(a: string, b: string): number {
  const [l1, a1, b1] = toLab(a);
  const [l2, a2, b2] = toLab(b);
  return (
    Math.round(Math.hypot(l1 - l2, a1 - a2, b1 - b2) * 10) / 10
  );
}

/** ΔE between two colours AS A DICHROMAT WOULD SEE THEM. */
export function cvdDeltaE(a: string, b: string, kind: CvdKind): number {
  return deltaE(simulateCvd(a, kind), simulateCvd(b, kind));
}

/** Every simulation at once — the row the gate report prints. */
export function cvdSeparation(a: string, b: string): Record<CvdKind, number> {
  return {
    protan: cvdDeltaE(a, b, "protan"),
    deutan: cvdDeltaE(a, b, "deutan"),
    tritan: cvdDeltaE(a, b, "tritan"),
  };
}
