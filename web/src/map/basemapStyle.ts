/**
 * The two legibility-tuned basemap styles (handoff 0043, design point 1).
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * The partner agency's ITS manager reported that when a dark theme was
 * applied, streets and geographic features became hard to read. That is
 * not an impression, it is measurable, and the measurement is damning —
 * the stock Protomaps flavors we shipped in handoff 0027 come out at:
 *
 *      stock dark   minor street vs ground   1.52:1     (bar: 3:1)
 *      stock dark   street name vs ground    2.11:1     (bar: 4.5:1)
 *      stock dark   water vs ground          1.34:1     (bar: 3:1)
 *      stock light  road casing vs ground    1.01:1     (bar: 3:1)
 *      stock light  street name vs ground    2.59:1     (bar: 4.5:1)
 *
 * A dark map that renders roads as dark grey on a dark ground buries the
 * network. The fix is not "darken less" — it is to INVERT the contrast:
 * keep the dark ground, and render roads, water and labels *lighter and
 * higher-contrast than the default*, so the street network ends up more
 * legible than the muddy vendor default. That is also the honest emphasis
 * for an ops map: the network you are reasoning about should dominate the
 * frame, and the land cover under it should not.
 *
 * BOTH styles are first-class and BOTH are authored. The light style is
 * not the vendor's and the dark one is not a filter of the light one —
 * every color in `styles/headway-basemap-{light,dark}.json` was chosen
 * against a measured target, and each style file carries its own check
 * list so the numbers are gated by test (`src/test/basemap-style.test.ts`)
 * and printable for the record (`npm run check:map-contrast`).
 *
 * WHAT WE REUSE AND WHY
 * ---------------------
 * The LAYER STRUCTURE (which `source-layer`, which `kind` filters, which
 * zoom stops) is the vendored Protomaps tile schema's contract, and it is
 * reused verbatim from `protomaps-themes-base` (BSD-3-Clause, ADR-0001
 * license gate) via its `*WithCustomTheme` entry points. Hand-copying ~70
 * layer definitions into our own JSON would fork that contract from the
 * archive our installer downloads and rot the first time either moves.
 * What is OURS — and what the ITS manager was complaining about — is the
 * paint: every color, the halo under every label, and the road widths.
 *
 * ZERO EXTERNAL REQUESTS (unchanged, and re-pinned by test)
 * --------------------------------------------------------
 * These styles name no tile server, no sprite and no font service. Every
 * label layer is forced onto the ONE vendored glyph stack under
 * `web/public/basemap-fonts/`; every `icon-image` is stripped and the POI
 * layer is dropped, because no sprite is vendored. The only URL in the
 * finished style is this installation's own origin.
 */

import type { LayerSpecification } from "maplibre-gl";
import {
  labelsWithCustomTheme,
  noLabelsWithCustomTheme,
  type Theme,
} from "protomaps-themes-base";
import darkStyleJson from "./styles/headway-basemap-dark.json";
import lightStyleJson from "./styles/headway-basemap-light.json";
import type { ContrastCheck } from "./contrast.ts";

/**
 * The street-style choice is DELIBERATELY INDEPENDENT of the app theme
 * (first-agency UAT 2026-07-29, restated in handoff 0043): in dark chrome
 * the dark streets were hard to read while the rest of the chrome was
 * right. Map legibility is a task decision, not a branding one. LIGHT is
 * the default in both app themes — the ITS manager found the light map
 * legible, so the contrast-tuned dark map is the opt-in.
 */
export type BasemapStyleId = "light" | "dark";

/** The shape of an authored style file. */
export interface BasemapStyleFile {
  id: BasemapStyleId;
  /** Human name, shown in the map legend. */
  name: string;
  /** Why this style is shaped the way it is (recorded rationale). */
  summary: string;
  /** Halo applied to EVERY label layer so no name dissolves into the
   *  ground. Upstream ships 1px flat; both our styles raise it. */
  labelHalo: { width: number; blur: number };
  /** Multiplier on every road line-width. Bright hairlines on a dark
   *  ground read thinner than dark ones on a light ground, so the dark
   *  style compensates. */
  roadWidthScale: number;
  /** The bars this style holds itself to (recorded next to the colors). */
  contrastTargets: { road: number; water: number; label: number };
  /** The gate, expressed as theme keys — see `contrast.ts`. */
  contrastChecks: ContrastCheck[];
  /** The authored palette, in the vendored schema's own vocabulary. */
  theme: Record<string, unknown>;
}

const STYLE_FILES: Record<BasemapStyleId, BasemapStyleFile> = {
  light: lightStyleJson as unknown as BasemapStyleFile,
  dark: darkStyleJson as unknown as BasemapStyleFile,
};

/** Both authored styles, for tests, the contrast report and the UI. */
export const BASEMAP_STYLES = STYLE_FILES;

export function basemapStyleFile(id: BasemapStyleId): BasemapStyleFile {
  return STYLE_FILES[id];
}

/**
 * The single vendored glyph stack (web/public/basemap-fonts — Noto Sans
 * Regular, SIL OFL 1.1). Every label layer is rewritten onto it so no
 * request for an unvendored font can ever fire.
 */
export const BASEMAP_FONT = "Noto Sans Regular";

/** Layer ids we never draw, whatever the vendored schema offers. */
const DROPPED_LAYER_IDS = new Set([
  // Our own token canvas stays behind everything, so the area outside the
  // extracted region looks unchanged.
  "background",
  // No sprite is vendored (v0 limitation, stated in the legend) — a POI
  // layer would be a request we refuse to make.
  "pois",
]);

/** Ids are namespaced so the overlay's own layer ids can never collide. */
export const BASEMAP_LAYER_PREFIX = "basemap-";

/**
 * Multiply a MapLibre line-width — a plain number, or an `interpolate`
 * expression whose OUTPUT stops are the widths (`[..., z0, w0, z1, w1]`).
 * Anything else is returned untouched rather than mangled.
 */
export function scaleLineWidth(value: unknown, scale: number): unknown {
  if (scale === 1) return value;
  if (typeof value === "number") return round3(value * scale);
  if (!Array.isArray(value) || value[0] !== "interpolate") return value;
  const out = [...value];
  // ["interpolate", <interpolation>, <input>, stop0, out0, stop1, out1, …]
  for (let i = 4; i < out.length; i += 2) {
    if (typeof out[i] === "number") out[i] = round3((out[i] as number) * scale);
  }
  return out;
}

function round3(n: number): number {
  return Math.round(n * 1000) / 1000;
}

/**
 * Road lines (not their labels) — the layers `roadWidthScale` applies to.
 * Takes the layer's ORIGINAL (un-namespaced) id: by the time a layer is
 * pushed it is called `basemap-roads_minor`, and matching on the prefixed
 * id would silently match nothing.
 */
function isRoadLine(layer: LayerSpecification, sourceId: string): boolean {
  return (
    layer.type === "line" &&
    sourceId.startsWith("roads_") &&
    !sourceId.startsWith("roads_labels")
  );
}

/**
 * Build the street layers for one authored style, adapted to this page:
 *   - the vendor's own background and POI layers dropped (above);
 *   - ids namespaced `basemap-*`;
 *   - every label forced onto the one vendored glyph stack, every
 *     `icon-image` stripped (no sprite is served);
 *   - a halo on EVERY label layer at this style's width/blur, falling
 *     back to the ground color if the schema left one without a halo
 *     color — a label with no halo is the failure mode we are fixing;
 *   - road widths scaled by this style's `roadWidthScale`.
 *
 * Pure: it returns fresh objects and never mutates the vendored specs.
 */
export function basemapLayerSpecs(id: BasemapStyleId): LayerSpecification[] {
  const style = STYLE_FILES[id];
  const theme = style.theme as unknown as Theme;
  const ground = String(style.theme.earth);
  const specs = [
    ...noLabelsWithCustomTheme("basemap", theme),
    ...labelsWithCustomTheme("basemap", theme, "en"),
  ] as LayerSpecification[];

  const out: LayerSpecification[] = [];
  for (const spec of specs) {
    if (DROPPED_LAYER_IDS.has(spec.id)) continue;
    const layer = structuredClone(spec) as LayerSpecification;
    const sourceId = layer.id;
    layer.id = `${BASEMAP_LAYER_PREFIX}${sourceId}`;

    if (layer.type === "symbol") {
      const layout = (layer.layout ?? {}) as Record<string, unknown>;
      if (layout["text-font"]) layout["text-font"] = [BASEMAP_FONT];
      delete layout["icon-image"];
      layer.layout = layout as typeof layer.layout;

      const paint = (layer.paint ?? {}) as Record<string, unknown>;
      if (typeof paint["text-halo-color"] !== "string") {
        paint["text-halo-color"] = ground;
      }
      paint["text-halo-width"] = style.labelHalo.width;
      paint["text-halo-blur"] = style.labelHalo.blur;
      layer.paint = paint as typeof layer.paint;
    }

    if (isRoadLine(layer, sourceId)) {
      const paint = (layer.paint ?? {}) as Record<string, unknown>;
      if (paint["line-width"] !== undefined) {
        paint["line-width"] = scaleLineWidth(
          paint["line-width"],
          style.roadWidthScale,
        );
        layer.paint = paint as typeof layer.paint;
      }
    }

    out.push(layer);
  }
  return out;
}
