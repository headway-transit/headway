/**
 * Developer tool (see index.html): renders ONE authored basemap style over
 * this installation's real PMTiles archive so a person can look at it.
 *
 * It deliberately imports the shipped modules — `basemapLayerSpecs` and the
 * style files themselves — rather than restating any color, so a preview can
 * never flatter a style the app does not actually draw.
 *
 * Not in the production artifact: `vite build` has a single HTML input.
 */

import { Map as MapLibreMap, addProtocol, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { PMTiles, Protocol as PmtilesProtocol } from "pmtiles";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import {
  BASEMAP_STYLES,
  basemapLayerSpecs,
  type BasemapStyleId,
} from "../../src/map/basemapStyle.ts";
import { measureStyle } from "../../src/map/contrast.ts";

setWorkerUrl(maplibreWorkerUrl);
addProtocol("pmtiles", new PmtilesProtocol().tile);

const BASEMAP_PATH = "/basemap/region.pmtiles";
const params = new URLSearchParams(window.location.search);
const styleId: BasemapStyleId = params.get("style") === "dark" ? "dark" : "light";
const style = BASEMAP_STYLES[styleId];

const caption = document.getElementById("caption") as HTMLParagraphElement;
if (styleId === "dark") caption.classList.add("on-dark");

const results = measureStyle(style);
const worstRoad = Math.min(
  ...results.filter((r) => r.kind !== "label").map((r) => r.best),
);
const worstLabel = Math.min(
  ...results.filter((r) => r.kind === "label").map((r) => r.best),
);
caption.textContent =
  `${style.name} — worst measured street/water contrast ${worstRoad.toFixed(2)}:1 ` +
  `(bar ${style.contrastTargets.road}:1), worst label ${worstLabel.toFixed(2)}:1 ` +
  `(bar ${style.contrastTargets.label}:1) · © OpenStreetMap contributors · Protomaps`;

async function main(): Promise<void> {
  // Frame the archive on its own recorded center unless the URL overrides it,
  // so the preview always lands inside the extracted region.
  const header = await new PMTiles(
    `${window.location.origin}${BASEMAP_PATH}`,
  ).getHeader();
  const lng = Number(params.get("lng") ?? header.centerLon);
  const lat = Number(params.get("lat") ?? header.centerLat);
  const zoom = Number(params.get("zoom") ?? 14);

  const map = new MapLibreMap({
    container: "map",
    style: {
      version: 8,
      glyphs: `${window.location.origin}/basemap-fonts/{fontstack}/{range}.pbf`,
      sources: {
        basemap: {
          type: "vector",
          url: `pmtiles://${window.location.origin}${BASEMAP_PATH}`,
          attribution: "© OpenStreetMap contributors · Protomaps",
        },
      },
      layers: [
        {
          id: "background",
          type: "background",
          paint: { "background-color": String(style.theme.background) },
        },
        ...basemapLayerSpecs(styleId),
      ],
    },
    center: [lng, lat],
    zoom,
    attributionControl: false,
    canvasContextAttributes: { preserveDrawingBuffer: true },
  });

  // A screenshot harness needs to know when there is something to capture.
  map.on("idle", () => {
    document.body.dataset.mapIdle = "true";
  });
}

void main();
