/**
 * The overlay layer stack (handoff 0043, design points 4, 6 and 7), in one
 * place so there is exactly ONE definition of what Headway draws on top of
 * the basemap.
 *
 * WHY IT IS A MODULE AND NOT INLINE IN THE VIEW
 * --------------------------------------------
 * The first half of this wave made a rule out of a near-miss: the developer
 * preview page imports the SHIPPED `basemapLayerSpecs()` rather than
 * restating any colour, "so a preview cannot flatter a style the app does
 * not draw". The screenshots in this half's evidence show the marks, a
 * flagged finding and the inspector, so the same rule has to cover the
 * overlay: the preview and `/map` both build their layers from here.
 *
 * ORDER IS MEANING
 * ----------------
 * Bottom to top: route lines, stops, the vehicle marks, the selection ring,
 * then the flagged-findings ring, glyph and label. Findings sit above the
 * fleet on purpose — the whole point of a flag is that it is not something
 * you have to hunt for. The basemap's own street layers are inserted BELOW
 * `routes-line` by the view, so every one of these draws over the streets.
 */

import type { LayerSpecification } from "maplibre-gl";
import { BASEMAP_FONT } from "./basemapStyle.ts";
import {
  FINDING_GLYPH,
  MARK_HALO,
  MARK_HALO_WIDTH,
  TOKEN_MARK_COLORS,
  modeColorExpression,
  modeFilterOpacityExpression,
  modeGlyphExpression,
  modeSizeExpression,
  routeColorExpression,
  routeOpacityExpression,
  routeWidthExpression,
  type MarkGround,
} from "./marks.ts";
import { PULSE_STATIC } from "./pulse.ts";

export const ROUTES_LAYER = "routes-line";
export const STOPS_LAYER = "stops-dot";
export const VEHICLE_MARK_LAYER = "vehicles-mark";
export const VEHICLE_SELECTED_LAYER = "vehicles-selected";
export const FINDINGS_PULSE_LAYER = "findings-pulse";
export const FINDINGS_MARK_LAYER = "findings-mark";
export const FINDINGS_LABEL_LAYER = "findings-label";

export interface OverlayLayerOptions {
  /** Which ground the marks sit on — decides the whole mark palette. */
  ground: MarkGround;
  /** The app's own route/stop tokens, resolved by the caller from CSS. */
  routeColor: string;
  stopColor: string;
  /** The highlighted mode, or null for "all". */
  selectedMode?: string | null;
}

export function overlayLayerSpecs({
  ground,
  routeColor,
  stopColor,
  selectedMode = null,
}: OverlayLayerOptions): LayerSpecification[] {
  return [
    {
      id: ROUTES_LAYER,
      type: "line",
      source: "routes",
      paint: {
        "line-color": routeColorExpression(routeColor, ground),
        "line-width": routeWidthExpression(selectedMode),
        "line-opacity": routeOpacityExpression(selectedMode),
      },
    },
    {
      id: STOPS_LAYER,
      type: "circle",
      source: "stops",
      paint: {
        "circle-radius": 2,
        "circle-color": stopColor,
        "circle-opacity": 0.75,
      },
    },
    // The mode mark. Shape, colour and size are ONE data-driven expression
    // each over the `mode` property — no per-feature DOM marker, no layer
    // per mode. `text-allow-overlap` + `text-ignore-placement` are
    // non-negotiable: MapLibre's default label collision would silently
    // HIDE vehicles in a busy depot, and a vehicle missing from the map is
    // exactly the kind of quiet gap this product exists to refuse.
    {
      id: VEHICLE_MARK_LAYER,
      type: "symbol",
      source: "vehicles",
      layout: {
        "text-field": modeGlyphExpression(),
        "text-font": [BASEMAP_FONT],
        "text-size": modeSizeExpression(),
        "text-allow-overlap": true,
        "text-ignore-placement": true,
      },
      paint: {
        "text-color": modeColorExpression(ground),
        "text-halo-color": MARK_HALO[ground],
        "text-halo-width": MARK_HALO_WIDTH,
        "text-opacity": modeFilterOpacityExpression(selectedMode),
      },
    },
    {
      id: VEHICLE_SELECTED_LAYER,
      type: "circle",
      source: "vehicles",
      filter: ["==", ["get", "vehicle_id"], ""],
      paint: {
        "circle-radius": 11,
        "circle-color": "rgba(0,0,0,0)",
        "circle-stroke-width": 2.5,
        // The identity accent: "this is what you are pointing at". Never a
        // status, on a map or anywhere else.
        "circle-stroke-color": TOKEN_MARK_COLORS.signal[ground],
      },
    },
    // The attention ring on a flagged finding: a FRAME, never a fill, so
    // the glow can never sit behind a figure. Animated by the view's
    // requestAnimationFrame loop over at most FLAG_CAP features.
    {
      id: FINDINGS_PULSE_LAYER,
      type: "circle",
      source: "findings",
      paint: {
        "circle-radius": PULSE_STATIC.radius,
        "circle-color": "rgba(0,0,0,0)",
        "circle-stroke-width": PULSE_STATIC.strokeWidth,
        "circle-stroke-color": TOKEN_MARK_COLORS.alert[ground],
        "circle-stroke-opacity": PULSE_STATIC.strokeOpacity,
      },
    },
    // Shape AND label, so a flag survives for anyone who never perceives
    // the pulse. ▲ is reserved for findings and is never a mode.
    {
      id: FINDINGS_MARK_LAYER,
      type: "symbol",
      source: "findings",
      layout: {
        "text-field": FINDING_GLYPH,
        "text-font": [BASEMAP_FONT],
        "text-size": 15,
        "text-allow-overlap": true,
        "text-ignore-placement": true,
      },
      paint: {
        "text-color": TOKEN_MARK_COLORS.alert[ground],
        "text-halo-color": MARK_HALO[ground],
        "text-halo-width": MARK_HALO_WIDTH,
      },
    },
    {
      id: FINDINGS_LABEL_LAYER,
      type: "symbol",
      source: "findings",
      layout: {
        "text-field": ["get", "label"],
        "text-font": [BASEMAP_FONT],
        "text-size": 11,
        "text-anchor": "top",
        "text-offset": [0, 1.4],
        "text-allow-overlap": true,
        "text-ignore-placement": true,
      },
      paint: {
        "text-color": TOKEN_MARK_COLORS.alert[ground],
        "text-halo-color": MARK_HALO[ground],
        "text-halo-width": MARK_HALO_WIDTH,
      },
    },
  ];
}
