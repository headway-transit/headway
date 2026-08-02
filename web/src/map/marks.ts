/**
 * Mode-aware vehicle marks and the flagged-findings mark (handoff 0043,
 * design points 4 and 6).
 *
 * THE SPRITE QUESTION, ANSWERED
 * -----------------------------
 * The design sketch asked for "a symbol layer over a self-hosted sprite for
 * the mode shapes". The first half of this wave recorded why that is not a
 * default: **no sprite sheet is vendored**, both authored styles
 * deliberately declare no `sprite`, and the POI layer is dropped precisely
 * because adding one would be a new binary asset through the
 * download-basemap pipeline and the ADR-0001 license gate.
 *
 * We did not add one. The shapes come from the glyph stack this
 * installation ALREADY vendors and already draws every street name with —
 * `web/public/basemap-fonts/Noto Sans Regular/` (SIL OFL 1.1), whose
 * 9472-9727 range carries the whole Unicode "Geometric Shapes" block
 * (U+25A0–U+25FF). A `symbol` layer with a data-driven `text-field` of
 * ●, ■, ◆, ▬, ○ and ▲ therefore gives shape encoding with:
 *   - zero new assets, zero new licenses, zero external requests;
 *   - no `sprite` key added to either style (the recorded v0 posture holds);
 *   - full data-driven paint — `text-color`, `text-halo-color` and
 *     `text-opacity` are all data-driven properties, so mode colour, the
 *     ground-contrast halo and the mode filter are ONE expression each.
 * A test reads the vendored .pbf and asserts every codepoint we draw is
 * actually in it, so a re-vendored font subset that dropped these glyphs
 * fails the build instead of silently erasing the fleet.
 *
 * WHY COLOUR IS THE SECOND CHANNEL, NOT THE FIRST
 * -----------------------------------------------
 * Ten canonical modes cannot all be told apart by hue — not by anyone, and
 * least of all by a viewer with a colour-vision deficiency. So:
 *   - SHAPE carries the mode FAMILY (road / rail / water / cable / unknown);
 *   - COLOUR separates the modes INSIDE one family, and only those pairs
 *     have to survive a CVD simulation — a different family is already a
 *     different glyph;
 *   - every same-shape pair is ALSO separated by relative luminance (a
 *     distinct brightness tier each), a channel no colour-vision deficiency
 *     removes;
 *   - and the vehicle list beside the map names every vehicle's mode in
 *     words, so nothing on this map is signalled by colour alone.
 *
 * The palette is GENERATED from (hue anchor × luminance tier) rather than
 * typed as hex, which is what makes the two guarantees above true by
 * construction instead of by luck: pick a tier and the contrast against the
 * ground is already decided. Both guarantees are then re-measured by test
 * against the palette that actually ships (`src/test/map-marks.test.ts`).
 *
 * HONESTY
 * -------
 * `mode` is NOT a field on the vehicle-positions payload. It is joined
 * client-side from the agency's OWN schedule data (the `mode` property the
 * /geometry/routes features already carry) through the vehicle's reported
 * `route_id`. A vehicle with no route_id, or a route_id we hold no route
 * for, is 'unknown' — drawn as the hollow ring, counted, and said in words.
 * Nothing here guesses a mode. See vehicles.ts.
 */

import type {
  DataDrivenPropertyValueSpecification,
  ExpressionSpecification,
} from "maplibre-gl";
import { BASEMAP_STYLES } from "./basemapStyle.ts";
import { fromLinearRgb, toLinearRgb } from "./cvd.ts";
import { luminance, ratio } from "./contrast.ts";

/**
 * The canonical mode vocabulary, mirroring the transform's GTFS
 * route_type→mode map (`headway_transform.gtfs_static.ROUTE_TYPE_TO_MODE`
 * plus `MODE_UNKNOWN`). The UI never invents a mode string: this list only
 * decides how a mode the SERVER sent is drawn. A mode outside this list is
 * still drawn — as the 'unknown' ring — and still named verbatim in the
 * list, so a vocabulary that grows is visible rather than silently dropped.
 */
export const CANONICAL_MODES = [
  "bus",
  "trolleybus",
  "rail",
  "subway",
  "tram",
  "monorail",
  "ferry",
  "cable_tram",
  "funicular",
  "aerial_lift",
  "unknown",
] as const;

export type MarkFamily = "road" | "rail" | "water" | "cable" | "unknown";

/** The ground a mark is drawn on: which basemap style (or, with no basemap
 *  downloaded, which app theme) owns the colour behind the marks. */
export type MarkGround = "light" | "dark";

/**
 * One glyph per family, from the vendored Noto Sans "Geometric Shapes"
 * block. ▲ is deliberately NOT a vehicle family — it is reserved for the
 * flagged-findings mark, so an upward triangle on this map always means
 * "a human needs to look at this" and never means a mode.
 */
export const FAMILY_GLYPH: Record<MarkFamily, string> = {
  road: "●", // ● BLACK CIRCLE
  rail: "■", // ■ BLACK SQUARE
  water: "◆", // ◆ BLACK DIAMOND
  cable: "▬", // ▬ BLACK RECTANGLE
  unknown: "○", // ○ WHITE CIRCLE — "we were not told", drawn hollow
};

/** The flagged-findings glyph. Reserved; never a mode. */
export const FINDING_GLYPH = "▲"; // ▲ BLACK UP-POINTING TRIANGLE

/**
 * Per-glyph size correction: these are typographic shapes, so the same
 * `text-size` does not put the same amount of ink on the map. Tuned against
 * the rendered screenshots, not guessed.
 */
export const FAMILY_SIZE: Record<MarkFamily, number> = {
  road: 15,
  rail: 13,
  water: 16,
  cable: 17,
  unknown: 16,
};

/**
 * Hue anchors. Okabe & Ito's colour-blind-safe qualitative set (Okabe M,
 * Ito K, "Color Universal Design", 2008), MINUS its two orange entries —
 * signal-orange is Headway's ONE non-semantic identity accent (handoff
 * 0041) and a mode must never be mistaken for it.
 *
 * These are anchors for HUE only. The luminance of the colour that ships is
 * set by its tier, below.
 */
const HUE_ANCHOR = {
  blue: "#0072B2",
  sky: "#56B4E9",
  green: "#009E73",
  yellow: "#F0E442",
  purple: "#CC79A7",
  neutral: "#6E7781",
} as const;

type HueName = keyof typeof HUE_ANCHOR;

/**
 * Relative-luminance tiers, per ground.
 *
 * Chosen so that (a) EVERY tier clears 3:1 against both grounds that
 * palette can be drawn on — WCAG 2.1 SC 1.4.11, the same bar the basemap
 * gate holds streets to, because a vehicle you cannot see is a vehicle that
 * is not on the map — and (b) consecutive tiers are far enough apart in
 * luminance to stay distinguishable with no colour perception at all.
 * Marks on the light ground are DARK, marks on the dark ground are LIGHT:
 * the contrast is inverted between the two, exactly as the two basemap
 * styles invert it for streets.
 */
const TIERS: Record<MarkGround, number[]> = {
  light: [0.01, 0.033, 0.08, 0.17],
  dark: [0.15, 0.27, 0.45, 0.7],
};

/**
 * The ground colours a mark can sit on, per palette.
 *
 * The basemap grounds are READ FROM THE AUTHORED STYLE FILES rather than
 * copied, so re-tuning a basemap ground automatically re-measures the
 * marks. The canvas grounds are the app's `--map-bg` tokens for the state
 * where no basemap has been downloaded (a test asserts they still match
 * `src/styles.css`, which this wave does not edit).
 */
export const MARK_GROUNDS: Record<MarkGround, Record<string, string>> = {
  light: {
    "light basemap earth": String(BASEMAP_STYLES.light.theme.earth),
    "outside the extract (background)": String(
      BASEMAP_STYLES.light.theme.background,
    ),
    "canvas ground, no basemap (--map-bg)": "#dce8f0",
  },
  dark: {
    "dark basemap earth": String(BASEMAP_STYLES.dark.theme.earth),
    "outside the extract (background)": String(
      BASEMAP_STYLES.dark.theme.background,
    ),
    "canvas ground, no basemap (--map-bg)": "#101823",
  },
};

/**
 * EVERY colour the matching basemap style can put underneath a mark —
 * flattened straight out of the authored palette, so a surface added later
 * is swept the day it appears. The first half of this wave learned this the
 * hard way: its first dark screenshot was of woodland, and a check that
 * only measured against `earth` would have passed a shoreline that was
 * really 2.80:1 against the leaf colour actually on screen. A vehicle mark
 * has exactly the same problem, and street ink counts too — the basemap
 * layers all draw BELOW the marks, so a mark can land on a bright motorway
 * fill or on a place label as easily as on bare earth.
 */
export function markSurfaces(ground: MarkGround): [string, string][] {
  const style = BASEMAP_STYLES[ground];
  const seen = new Map<string, string>();
  const walk = (value: unknown, path: string): void => {
    if (typeof value === "string") {
      if (/^#[0-9A-Fa-f]{6}$/.test(value) && !seen.has(value)) {
        seen.set(value, path);
      }
      return;
    }
    if (value && typeof value === "object") {
      for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
        walk(v, path ? `${path}.${k}` : k);
      }
    }
  };
  walk(style.theme, "");
  for (const [name, color] of Object.entries(MARK_GROUNDS[ground])) {
    if (!seen.has(color)) seen.set(color, name);
  }
  return [...seen.entries()].map(([color, name]) => [name, color]);
}

/**
 * The halo every mark carries. It is what keeps a mark legible when it is
 * sitting ON a street rather than on the ground — a dark mark crossing a
 * dark road casing, or a light mark crossing a bright motorway fill. The
 * mark-vs-halo pair is gated at 3:1 too, so the outline is a real edge and
 * not a suggestion.
 */
export const MARK_HALO: Record<MarkGround, string> = {
  light: "#FFFFFF",
  dark: "#05070B",
};

/** Halo width in px (SDF text halo; kept under 1/4 of the glyph size). */
export const MARK_HALO_WIDTH = 1.8;

/**
 * Colours taken from the SHIPPED token set rather than invented here, one
 * value per ground: the light-theme value is used on light grounds and the
 * dark-theme value on dark grounds. They are literals because the map
 * canvas cannot resolve a CSS custom property, and a test asserts each one
 * still equals the value in `src/styles.css` — so this cannot drift out of
 * sync with the token system it is quoting, and this wave never edits that
 * file.
 */
export const TOKEN_MARK_COLORS = {
  /** `--status-alert`: the flagged-findings mark. Semantic, CVD-safe set. */
  alert: { light: "#9f1b1b", dark: "#f5514e" },
  /** `--signal`: the ONE non-semantic identity accent — used here for
   *  "this is what you are pointing at", never for a status or a mode. */
  signal: { light: "#a84400", dark: "#ff7a1a" },
} as const;

/** How each canonical mode is drawn: family (shape) + hue + tier. */
export const MODE_MARKS: Record<
  string,
  { family: MarkFamily; hue: HueName; tier: number }
> = {
  bus: { family: "road", hue: "blue", tier: 1 },
  trolleybus: { family: "road", hue: "sky", tier: 3 },
  rail: { family: "rail", hue: "purple", tier: 2 },
  subway: { family: "rail", hue: "blue", tier: 0 },
  tram: { family: "rail", hue: "green", tier: 1 },
  monorail: { family: "rail", hue: "yellow", tier: 3 },
  ferry: { family: "water", hue: "sky", tier: 1 },
  cable_tram: { family: "cable", hue: "green", tier: 2 },
  funicular: { family: "cable", hue: "purple", tier: 0 },
  aerial_lift: { family: "cable", hue: "yellow", tier: 3 },
  unknown: { family: "unknown", hue: "neutral", tier: 1 },
};

/** Straight-line mix of two colours in sRGB space. */
function mixSrgb(a: string, b: string, t: number): string {
  const pa = toLinearRgb(a);
  const pb = toLinearRgb(b);
  // Mix in the ENCODED (gamma) domain: it holds the hue of the anchor far
  // better than a linear-light mix, which washes saturated colours out.
  const enc = (v: number) =>
    v <= 0.0031308 ? v * 12.92 : 1.055 * Math.pow(v, 1 / 2.4) - 0.055;
  const dec = (v: number) =>
    v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  return fromLinearRgb([
    dec(enc(pa[0]) * (1 - t) + enc(pb[0]) * t),
    dec(enc(pa[1]) * (1 - t) + enc(pb[1]) * t),
    dec(enc(pa[2]) * (1 - t) + enc(pb[2]) * t),
  ]);
}

/**
 * The generator: take a hue anchor to an exact relative luminance by
 * blending it toward black or toward white, whichever direction it needs.
 *
 * Luminance is monotonic along that blend, so a bisection lands on the
 * target. This is the step that makes "every mark clears 3:1 against its
 * ground" true BY CONSTRUCTION rather than by a lucky hex value — the tier
 * is the promise and the colour is derived from it.
 */
export function colorAtLuminance(anchor: string, target: number): string {
  const toward = luminance(anchor) > target ? "#000000" : "#FFFFFF";
  let lo = 0;
  let hi = 1;
  let out = anchor;
  for (let i = 0; i < 24; i++) {
    const mid = (lo + hi) / 2;
    out = mixSrgb(anchor, toward, mid);
    if (luminance(out) > target === (toward === "#000000")) lo = mid;
    else hi = mid;
  }
  return out;
}

/** The mode → colour palette for one ground, generated from MODE_MARKS. */
export function markPalette(ground: MarkGround): Record<string, string> {
  const palette: Record<string, string> = {};
  for (const mode of CANONICAL_MODES) {
    const spec = MODE_MARKS[mode];
    palette[mode] = colorAtLuminance(
      HUE_ANCHOR[spec.hue],
      TIERS[ground][spec.tier],
    );
  }
  return palette;
}

/** The family (and therefore the glyph) for a mode the server sent. */
export function markFamily(mode: string): MarkFamily {
  return MODE_MARKS[mode]?.family ?? "unknown";
}

/** The colour a mode is drawn in on this ground. Unlisted → the ring. */
export function markColor(mode: string, ground: MarkGround): string {
  const palette = markPalette(ground);
  return palette[mode] ?? palette.unknown;
}

// ---- the data-driven expressions (one per visual channel) ----------------

/**
 * Build a `match` over the `mode` property. One expression per visual
 * channel, evaluated on the GPU over the whole source — the alternative
 * (a DOM marker per vehicle, or a layer per mode) does not survive a fleet.
 */
function matchOnMode<T>(
  valueFor: (mode: string) => T,
): ExpressionSpecification {
  const cases: unknown[] = [];
  for (const mode of CANONICAL_MODES) {
    if (mode === "unknown") continue;
    cases.push(mode, valueFor(mode));
  }
  // A mode string outside the canonical list falls through to the 'unknown'
  // ring rather than to nothing: an unrecognised mode is still DRAWN, and
  // the vehicle list still names it verbatim.
  return [
    "match",
    ["get", "mode"],
    ...cases,
    valueFor("unknown"),
  ] as unknown as ExpressionSpecification;
}

/** MapLibre expression: mode → its family's glyph. */
export function modeGlyphExpression(): ExpressionSpecification {
  return matchOnMode((mode) => FAMILY_GLYPH[markFamily(mode)]);
}

/** MapLibre expression: mode → its colour on this ground. */
export function modeColorExpression(
  ground: MarkGround,
): ExpressionSpecification {
  const palette = markPalette(ground);
  return matchOnMode((mode) => palette[mode] ?? palette.unknown);
}

/** MapLibre expression: mode → the size its glyph needs. */
export function modeSizeExpression(): ExpressionSpecification {
  return matchOnMode((mode) => FAMILY_SIZE[markFamily(mode)]);
}

/** Opacity used to DIM (never hide) the modes the filter is not on. */
export const MODE_DIM_OPACITY = 0.22;

/**
 * MapLibre expression for the mode filter: full strength for the selected
 * mode, dimmed for the rest. Nothing is removed and nothing is re-fetched —
 * this is one paint property, applied to the source already on the map.
 */
export function modeFilterOpacityExpression(
  selectedMode: string | null,
  full = 1,
): DataDrivenPropertyValueSpecification<number> {
  if (!selectedMode) return full;
  return [
    "case",
    ["==", ["get", "mode"], selectedMode],
    full,
    MODE_DIM_OPACITY,
  ] as unknown as ExpressionSpecification;
}

/**
 * Route line width: a related route (lit by the inspector's feature-state)
 * wins, then the selected mode is thickened, then the default hairline.
 */
export function routeWidthExpression(
  selectedMode: string | null,
): DataDrivenPropertyValueSpecification<number> {
  const modeWidth = selectedMode
    ? ["case", ["==", ["get", "mode"], selectedMode], 3.2, 1.2]
    : 1.5;
  return [
    "case",
    ["boolean", ["feature-state", "related"], false],
    4,
    modeWidth,
  ] as unknown as ExpressionSpecification;
}

/** Route line colour: related routes take the identity accent. */
export function routeColorExpression(
  baseColor: string,
  ground: MarkGround,
): DataDrivenPropertyValueSpecification<string> {
  return [
    "case",
    ["boolean", ["feature-state", "related"], false],
    TOKEN_MARK_COLORS.signal[ground],
    baseColor,
  ] as unknown as ExpressionSpecification;
}

/** Route line opacity: related stays full; otherwise the mode filter. */
export function routeOpacityExpression(
  selectedMode: string | null,
): DataDrivenPropertyValueSpecification<number> {
  return [
    "case",
    ["boolean", ["feature-state", "related"], false],
    1,
    modeFilterOpacityExpression(selectedMode, 0.85),
  ] as unknown as ExpressionSpecification;
}

// ---- the gate ------------------------------------------------------------

export interface MarkContrastResult {
  what: string;
  mode: string;
  ground: MarkGround;
  color: string;
  against: { key: string; color: string; ratio: number }[];
  worst: number;
  min: number;
  pass: boolean;
}

/** WCAG 2.1 SC 1.4.11 — meaningful non-text graphics. */
export const MARK_CONTRAST_MIN = 3;

/**
 * Measure EVERY mode colour against EVERY ground its palette can be drawn
 * on AND against its own halo. Generated from the palette, so a mode added
 * later is gated the day it appears — the same discipline as the basemap
 * gate's all-grounds sweep.
 */
export function markContrastResults(): MarkContrastResult[] {
  const out: MarkContrastResult[] = [];
  for (const ground of ["light", "dark"] as MarkGround[]) {
    const palette = markPalette(ground);
    const grounds = {
      ...MARK_GROUNDS[ground],
      "its own halo": MARK_HALO[ground],
    };
    for (const mode of CANONICAL_MODES) {
      const color = palette[mode];
      const against = Object.entries(grounds).map(([key, gc]) => ({
        key,
        color: gc,
        ratio: ratio(color, gc),
      }));
      const worst = against.reduce((a, m) => Math.min(a, m.ratio), Infinity);
      out.push({
        what: `${mode} mark on the ${ground} ground`,
        mode,
        ground,
        color,
        against,
        worst,
        min: MARK_CONTRAST_MIN,
        pass: worst >= MARK_CONTRAST_MIN,
      });
    }
    // The two token-sourced marks ride the same sweep.
    for (const [name, byGround] of Object.entries(TOKEN_MARK_COLORS)) {
      const color = byGround[ground];
      const against = Object.entries(grounds).map(([key, gc]) => ({
        key,
        color: gc,
        ratio: ratio(color, gc),
      }));
      const worst = against.reduce((a, m) => Math.min(a, m.ratio), Infinity);
      out.push({
        what: `${name} mark on the ${ground} ground`,
        mode: name,
        ground,
        color,
        against,
        worst,
        min: MARK_CONTRAST_MIN,
        pass: worst >= MARK_CONTRAST_MIN,
      });
    }
  }
  return out;
}

export interface MarkSurfaceResult {
  ground: MarkGround;
  mode: string;
  surface: string;
  surfaceColor: string;
  /** Ink straight against the surface. */
  inkRatio: number;
  /** The halo ring against the surface — what carries the mark when the
   *  ink itself happens to match whatever it landed on. */
  haloRatio: number;
  best: number;
  pass: boolean;
}

/**
 * The all-surfaces sweep.
 *
 * A mark is ink inside a halo, so it is perceivable over a surface when
 * EITHER the ink separates from that surface OR the halo does — given that
 * ink-vs-halo is separately gated at 3:1 (see `markContrastResults`). Both
 * numbers are always reported so a weak ink cannot hide behind a strong
 * halo, exactly as the basemap gate reports a road's fill and its casing.
 */
export function markSurfaceResults(): MarkSurfaceResult[] {
  const out: MarkSurfaceResult[] = [];
  for (const ground of ["light", "dark"] as MarkGround[]) {
    const palette = markPalette(ground);
    const halo = MARK_HALO[ground];
    for (const [surface, surfaceColor] of markSurfaces(ground)) {
      for (const mode of CANONICAL_MODES) {
        const inkRatio = ratio(palette[mode], surfaceColor);
        const haloRatio = ratio(halo, surfaceColor);
        const best = Math.max(inkRatio, haloRatio);
        out.push({
          ground,
          mode,
          surface,
          surfaceColor,
          inkRatio,
          haloRatio,
          best,
          pass: best >= MARK_CONTRAST_MIN,
        });
      }
    }
  }
  return out;
}

/** Every pair of modes that share a glyph — the pairs colour alone must
 *  separate, because for every other pair the shape already has. */
export function sameShapePairs(): [string, string][] {
  const byFamily = new Map<MarkFamily, string[]>();
  for (const mode of CANONICAL_MODES) {
    const family = MODE_MARKS[mode].family;
    byFamily.set(family, [...(byFamily.get(family) ?? []), mode]);
  }
  const pairs: [string, string][] = [];
  for (const modes of byFamily.values()) {
    for (let i = 0; i < modes.length; i++) {
      for (let j = i + 1; j < modes.length; j++) {
        pairs.push([modes[i], modes[j]]);
      }
    }
  }
  return pairs;
}

/**
 * The luminance-contrast ratio between two mode colours on one ground —
 * the channel that survives EVERY colour-vision deficiency, including the
 * ones the simulation approximates badly and monochromacy, which it does
 * not model at all.
 */
export function modeLuminanceSeparation(
  a: string,
  b: string,
  ground: MarkGround,
): number {
  const palette = markPalette(ground);
  return ratio(palette[a], palette[b]);
}
